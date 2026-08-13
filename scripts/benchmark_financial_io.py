from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from thesistrace.data.financial_candidate import FinancialCandidateStore
from thesistrace.data.financial_collection import (
    FINANCIAL_ENDPOINTS,
    CompletedFinancialCollection,
    FinancialCollectionContract,
    FinancialDateShard,
    FinancialShardCheckpoint,
    RawFinancialBatchStore,
)
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.data.io_benchmark import (
    assert_benchmark_budgets,
    derive_repository_budgets,
    measure_operation,
    summarize_samples,
)
from thesistrace.fixture import build_minimal_canonical_fixture
from thesistrace.publication.serialization import canonical_json_bytes

_ROOT = Path(__file__).resolve().parents[1]
_PROFILE_PATH = _ROOT / "benchmarks" / "financial-io-2010-profile.json"
_BUDGET_PATH = _ROOT / "benchmarks" / "financial-io-2010-budgets.json"
_POINTER = "benchmark-generation.json"
_IDENTITY_FIELDS = (
    "ts_code",
    "ann_date",
    "f_ann_date",
    "end_date",
    "report_type",
    "comp_type",
    "end_type",
)
_EXECUTABLE_FIELDS = {
    "income": ("total_revenue", "n_income_attr_p"),
    "balancesheet": ("total_assets", "total_liab", "total_hldr_eqy_exc_min_int"),
    "cashflow": ("n_cashflow_act",),
}
_WIDE_NON_NULL_STRIDE = 16


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the deterministic 2010-scale market/financial I/O benchmark."
    )
    parser.add_argument("--mount-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-budgets", action="store_true")
    parser.add_argument("--update-budgets", action="store_true")
    arguments = parser.parse_args()
    profile = _read_json(_PROFILE_PATH)
    if arguments.mount_root is None:
        with tempfile.TemporaryDirectory(prefix="thesistrace-financial-io-") as temporary:
            results = _run(Path(temporary), profile)
    else:
        arguments.mount_root.mkdir(parents=True, exist_ok=True)
        results = _run(arguments.mount_root.resolve(), profile)
    if not arguments.skip_budgets:
        assert_benchmark_budgets(results, _read_json(_BUDGET_PATH))
    if arguments.update_budgets:
        if not arguments.skip_budgets:
            raise RuntimeError("budget update requires --skip-budgets")
        _BUDGET_PATH.write_text(
            json.dumps(derive_repository_budgets(results), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    content = json.dumps(results, indent=2, sort_keys=True) + "\n"
    if arguments.output is None:
        print(content, end="")
    else:
        arguments.output.write_text(content, encoding="utf-8")


def _run(mount_root: Path, profile: dict[str, object]) -> dict[str, object]:
    generation = _prepare_generation(mount_root, profile)
    descriptor = MountedGenerationStore(mount_root).inspect_root(generation)
    execution_sessions = list(descriptor.research_sessions[-20:])
    repetitions = int(profile["repetitions_per_phase"])

    def operation(name: str, store: MountedGenerationStore) -> object:
        if name == "descriptor":
            return store.inspect_root(generation)
        if name == "price_only":
            return store.read_composite_slice(
                generation,
                sessions=execution_sessions,
                universe_name="top300",
                neutralization="none",
                field_bindings={"price.close.adjusted": "close_adj"},
            )
        if name == "financial_only":
            return store.read_composite_slice(
                generation,
                sessions=execution_sessions,
                universe_name="top300",
                neutralization="none",
                field_bindings={"total_assets_latest_reported": "total_assets_latest_reported"},
            )
        if name == "mixed":
            return store.read_composite_slice(
                generation,
                sessions=execution_sessions,
                universe_name="top300",
                neutralization="none",
                field_bindings={
                    "price.close.adjusted": "close_adj",
                    "total_assets_latest_reported": "total_assets_latest_reported",
                },
            )
        raise AssertionError(f"unknown benchmark scenario: {name}")

    scenarios: dict[str, object] = {}
    for name in ("descriptor", "price_only", "financial_only", "mixed"):
        cold = [
            measure_operation(
                lambda scenario=name: operation(scenario, MountedGenerationStore(mount_root)),
                cold=True,
            )
            for _ in range(repetitions)
        ]
        warm_store = MountedGenerationStore(mount_root)
        operation(name, warm_store)
        warm = [
            measure_operation(lambda scenario=name, store=warm_store: operation(scenario, store))
            for _ in range(repetitions)
        ]
        scenarios[name] = {
            "cold": summarize_samples(cold),
            "warm": summarize_samples(warm),
        }
    scenarios["tracking_advance"] = _tracking_advance_benchmark(
        mount_root,
        generation,
        descriptor.research_sessions,
        repetitions,
    )
    _assert_selective_io(scenarios)
    return {
        "format": "thesistrace-financial-io-baseline",
        "version": 1,
        "profile": profile,
        "generation_manifest_sha256": generation,
        "scenarios": scenarios,
    }


def _tracking_advance_benchmark(
    mount_root: Path,
    generation: str,
    sessions: tuple[str, ...],
    repetitions: int,
) -> dict[str, object]:
    from thesistrace.data.lifecycle import DatasetLifecycle
    from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime
    from thesistrace.entrypoints.schema import initialize_core

    settings = CoreSettings.from_environment()
    if settings.data_mount.resolve() != mount_root:
        raise RuntimeError("benchmark runtime and mount root differ")
    initialize_core(settings.database_url)
    from thesistrace._postgres import PostgresDatabase

    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, mount_root)
        if lifecycle.current_pointer() is not None:
            raise RuntimeError("benchmark requires an empty Dataset Head")
        lifecycle.protect_candidate(
            operation_id="financial-io-benchmark-head",
            generation_manifest_sha256=generation,
            lease_seconds=3600,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=None,
            candidate_generation_manifest_sha256=generation,
            operation_id="financial-io-benchmark-head",
        )
    finally:
        database.close()

    with open_core_runtime(settings) as runtime:
        cold_tracks = [
            _activate_benchmark_track(runtime, sessions, f"cold-{index}")
            for index in range(repetitions)
        ]
        cold = [
            measure_operation(runtime.daily_tracks.process_next, cold=True)
            for _track_id in cold_tracks
        ]
        _stop_benchmark_tracks(runtime, cold_tracks, "cold")

        preload = _activate_benchmark_track(runtime, sessions, "warm-preload")
        if runtime.daily_tracks.process_next() is not True:
            raise RuntimeError("tracking benchmark preload was not processed")
        _stop_benchmark_tracks(runtime, [preload], "warm-preload")
        warm_tracks = [
            _activate_benchmark_track(runtime, sessions, f"warm-{index}")
            for index in range(repetitions)
        ]
        warm = [measure_operation(runtime.daily_tracks.process_next) for _track_id in warm_tracks]
        _stop_benchmark_tracks(runtime, warm_tracks, "warm")
    return {
        "cold": summarize_samples(cold),
        "warm": summarize_samples(warm),
    }


def _activate_benchmark_track(runtime: object, sessions: tuple[str, ...], suffix: str) -> str:
    from thesistrace.definition.models import DefinitionRunCommand
    from thesistrace.research_run.models import StartTrackingCommand

    outcome = runtime.definitions.run(
        None,
        DefinitionRunCommand(
            request_id=f"financial-io-benchmark-run-{suffix}",
            name=f"Financial I/O benchmark {suffix}",
            alpha={
                "operator_id": "add",
                "operands": [
                    {"field_id": "price.close.adjusted"},
                    {"field_id": "total_assets_latest_reported"},
                ],
            },
            universe="top300",
            neutralization="none",
            holdings_count=10,
            rebalance_every_sessions=1,
            start_date=sessions[-22],
            end_date=sessions[-2],
        ),
    )
    if outcome.outcome != "accepted" or outcome.run is None:
        raise RuntimeError("tracking benchmark seed Run was rejected")
    if runtime.research_runs.process_next() is not True:
        raise RuntimeError("tracking benchmark seed Run was not processed")
    track = runtime.research_runs.start_tracking(
        outcome.run.id,
        StartTrackingCommand(request_id=f"financial-io-benchmark-track-{suffix}"),
    )
    if track is None:
        raise RuntimeError("tracking benchmark Track was not activated")
    return track.id


def _stop_benchmark_tracks(runtime: object, track_ids: list[str], suffix: str) -> None:
    from thesistrace.daily_track.models import StopDailyTrackCommand

    for index, track_id in enumerate(track_ids):
        stopped = runtime.daily_tracks.stop(
            track_id,
            StopDailyTrackCommand(request_id=f"financial-io-benchmark-stop-{suffix}-{index}"),
        )
        if stopped is None or stopped.status != "stopped":
            raise RuntimeError("tracking benchmark Track was not stopped")


def _prepare_generation(mount_root: Path, profile: dict[str, object]) -> str:
    pointer = mount_root / _POINTER
    profile_sha256 = hashlib.sha256(canonical_json_bytes(profile)).hexdigest()
    if pointer.exists():
        value = _read_json(pointer)
        if value.get("profile_sha256") != profile_sha256:
            raise RuntimeError("benchmark mount contains a different profile")
        generation = str(value.get("generation_manifest_sha256"))
        MountedGenerationStore(mount_root).validate_generation(generation)
        return generation

    sessions = _weekdays(str(profile["calendar_start"]), str(profile["calendar_end"]))
    instrument_count = int(profile["ordinary_a_share_instrument_count"])
    universe_size = int(profile["execution_universe_size"])
    dense_count = int(profile["market_dense_session_count"])
    market_store = MountedGenerationStore(mount_root)
    market = market_store.materialize(
        _market_fixture(sessions, instrument_count, universe_size, dense_count),
        prepared_at=datetime(2026, 8, 13, 9, tzinfo=UTC),
        source_name="financial-io-2010-benchmark",
        source_lineage={"profile_sha256": profile_sha256},
    )
    financial = _financial_candidate(
        mount_root,
        market.manifest_sha256,
        sessions,
        profile,
    )
    composite = market_store.compose_financial_candidate(
        market.manifest_sha256,
        financial,
        prepared_at=datetime(2026, 8, 13, 10, tzinfo=UTC),
    )
    pointer.write_bytes(
        canonical_json_bytes(
            {
                "profile_sha256": profile_sha256,
                "generation_manifest_sha256": composite.manifest_sha256,
            }
        )
    )
    return composite.manifest_sha256


def _market_fixture(
    sessions: list[str],
    instrument_count: int,
    universe_size: int,
    dense_count: int,
) -> dict[str, object]:
    template = build_minimal_canonical_fixture()
    instruments = [_instrument(index, sessions[0]) for index in range(1, instrument_count + 1)]
    instrument_ids = [str(item["instrument_id"]) for item in instruments]
    dense_sessions = sessions[-dense_count:]
    prices: list[dict[str, object]] = []
    states: list[dict[str, object]] = []
    limits: list[dict[str, object]] = []
    price_template = dict(template["prices"][0])
    state_template = dict(template["trading_states"][0])
    limit_template = dict(template["price_limits"][0])
    base_pool: list[dict[str, object]] = []
    universes = {name: [] for name in ("top300", "top1000", "top2000", "top3000")}
    represented_instruments: set[str] = set()
    for session_index, session in enumerate(dense_sessions):
        rotation = ((session_index // 64) * universe_size) % instrument_count
        ranking = instrument_ids[rotation:] + instrument_ids[:rotation]
        selected = ranking[:universe_size]
        represented_instruments.update(selected)
        for instrument_id in selected:
            prices.append(dict(price_template, session=session, instrument_id=instrument_id))
            states.append(dict(state_template, session=session, instrument_id=instrument_id))
            limits.append(dict(limit_template, session=session, instrument_id=instrument_id))
        base_pool.append({"session": session, "instrument_ids": selected})
        for name in universes:
            universes[name].append(
                {"session": session, "instrument_ids": selected, "status": "available"}
            )
    if represented_instruments != set(instrument_ids):
        raise RuntimeError("benchmark market rotation does not represent every instrument")
    empty_sessions = sessions[: len(sessions) - len(dense_sessions)]
    base_pool = [
        *({"session": session, "instrument_ids": []} for session in empty_sessions),
        *base_pool,
    ]
    for name in universes:
        universes[name] = [
            *(
                {"session": session, "instrument_ids": [], "status": "available"}
                for session in empty_sessions
            ),
            *universes[name],
        ]
    field = dict(template["field_catalog"][0])
    field["release_available_from"] = sessions[0]
    return {
        "schema_version": "canonical-eod",
        "research_calendar": sessions,
        "instruments": instruments,
        "prices": prices,
        "trading_states": states,
        "price_limits": limits,
        "base_pool": base_pool,
        "liquidity_universes": universes,
        "industry_membership": [
            {
                "instrument_id": item["instrument_id"],
                "active_from": sessions[0],
                "active_to": "",
                "sw2021_l1": f"Industry-{index % 31:02d}",
                "sw2021_l2": f"Industry-{index % 31:02d}",
                "sw2021_l3": f"Industry-{index % 31:02d}",
            }
            for index, item in enumerate(instruments)
        ],
        "field_catalog": [field],
    }


def _financial_candidate(
    mount_root: Path,
    market_generation: str,
    sessions: list[str],
    profile: dict[str, object],
) -> str:
    counts = profile["statement_source_field_counts"]
    if not isinstance(counts, dict):
        raise RuntimeError("benchmark statement field profile is invalid")
    if profile.get("wide_non_null_stride") != _WIDE_NON_NULL_STRIDE:
        raise RuntimeError("benchmark wide-field sparsity contract is invalid")
    fields = {
        endpoint: _wide_fields(endpoint, int(counts[endpoint])) for endpoint in FINANCIAL_ENDPOINTS
    }
    raw = RawFinancialBatchStore(mount_root)
    checkpoints: list[FinancialShardCheckpoint] = []
    expected_versions = int(profile["financial_versions_per_instrument_endpoint"])
    for index in range(1, int(profile["ordinary_a_share_instrument_count"]) + 1):
        ts_code = f"{index:06d}.SZ"
        instrument_id = f"equity:{ts_code}"
        for endpoint in FINANCIAL_ENDPOINTS:
            items = _financial_items(endpoint, fields[endpoint], ts_code, index)
            if len(items) != expected_versions:
                raise RuntimeError("benchmark Financial Version count is invalid")
            payload_sha256 = hashlib.sha256(
                canonical_json_bytes({"fields": list(fields[endpoint]), "items": items})
            ).hexdigest()
            payload = {
                "format": "thesistrace-raw-financial-batch",
                "version": 1,
                "source_contract_version": "tushare-financial-ordinary-v1",
                "endpoint": endpoint,
                "parameters": {"ts_code": ts_code},
                "returned_fields": list(fields[endpoint]),
                "items": items,
                "row_count": len(items),
                "source_date_extent": ["20100425", "20260425"],
                "payload_sha256": payload_sha256,
            }
            checkpoints.append(
                FinancialShardCheckpoint(
                    ordinal=len(checkpoints),
                    endpoint=endpoint,
                    instrument_id=instrument_id,
                    ts_code=ts_code,
                    shard="complete-history",
                    status="completed",
                    batch_sha256=raw.store(canonical_json_bytes(payload)),
                    collected_at="2026-08-13T08:00:00+00:00",
                    first_observed_at="2026-08-13T08:00:00+00:00",
                )
            )
    contract = FinancialCollectionContract(
        capability_sha256=hashlib.sha256(
            canonical_json_bytes({key: list(value) for key, value in fields.items()})
        ).hexdigest(),
        endpoint_fields=tuple((endpoint, fields[endpoint]) for endpoint in FINANCIAL_ENDPOINTS),
        suspected_truncation_row_counts=tuple((endpoint, None) for endpoint in FINANCIAL_ENDPOINTS),
        shards=(FinancialDateShard("complete-history"),),
    )
    candidate = FinancialCandidateStore(mount_root).materialize(
        CompletedFinancialCollection(
            idempotency_key="financial-io-2010-benchmark",
            generation_manifest_sha256=market_generation,
            contract=contract,
            finished_at="2026-08-13T09:00:00+00:00",
            target_count=len(checkpoints),
            shards=tuple(checkpoints),
        ),
        observation_through_session=sessions[-1],
    )
    return candidate.manifest_sha256


def _wide_fields(endpoint: str, count: int) -> tuple[str, ...]:
    fixed = (*_IDENTITY_FIELDS, *_EXECUTABLE_FIELDS[endpoint], "update_flag")
    if count < len(fixed):
        raise RuntimeError("benchmark source field count is too small")
    return (
        *fixed[:-1],
        *(f"{endpoint}_retained_{index:03d}" for index in range(count - len(fixed))),
        fixed[-1],
    )


def _financial_items(
    endpoint: str,
    fields: tuple[str, ...],
    ts_code: str,
    index: int,
) -> list[list[object]]:
    rows: list[list[object]] = []
    for year in range(2009, 2026):
        published = f"{year + 1}0425"
        report_period = f"{year}1231"
        for revision in range(2):
            offset = (year - 2009) * 2 + revision
            rows.append(
                _financial_item(
                    endpoint,
                    fields,
                    ts_code,
                    index,
                    published,
                    report_period,
                    offset,
                    revision,
                )
            )
    return rows


def _financial_item(
    endpoint: str,
    fields: tuple[str, ...],
    ts_code: str,
    index: int,
    published: str,
    report_period: str,
    offset: int,
    revision: int,
) -> list[object]:
    values: dict[str, object] = {
        "ts_code": ts_code,
        "ann_date": published,
        "f_ann_date": "",
        "end_date": report_period,
        "report_type": "1",
        "comp_type": "1",
        "end_type": "4",
        "update_flag": str(revision),
    }
    values.update(
        {
            field: str(index * 100 + offset + field_index)
            for field_index, field in enumerate(_EXECUTABLE_FIELDS[endpoint], start=1)
        }
    )
    retained_wide_value = str(index * 1000 + offset)
    return [
        values[field]
        if field in values
        else (
            retained_wide_value
            if (index + offset + field_index) % _WIDE_NON_NULL_STRIDE == 0
            else None
        )
        for field_index, field in enumerate(fields)
    ]


def _instrument(index: int, listed_from: str) -> dict[str, str]:
    ts_code = f"{index:06d}.SZ"
    return {
        "instrument_id": f"equity:{ts_code}",
        "ts_code": ts_code,
        "asset_type": "ordinary_a_share",
        "exchange": "SZSE",
        "board": "main",
        "listed_from": listed_from,
        "listed_to": "",
    }


def _weekdays(start: str, end: str) -> list[str]:
    current = date.fromisoformat(start)
    final = date.fromisoformat(end)
    sessions: list[str] = []
    while current <= final:
        if current.weekday() < 5:
            sessions.append(current.isoformat())
        current += timedelta(days=1)
    return sessions


def _assert_selective_io(scenarios: dict[str, object]) -> None:
    for phase in ("cold", "warm"):
        descriptor = scenarios["descriptor"][phase]["p95"]
        if descriptor["parquet_object_opens"] != 0 or descriptor["rows_scanned"] != 0:
            raise AssertionError("descriptor benchmark opened Parquet")
        price = scenarios["price_only"][phase]["p95"]
        if price["financial_parquet_scans"] != 0 or price["raw_financial_batch_opens"] != 0:
            raise AssertionError("price-only benchmark opened Financial Data")
        for scenario in ("financial_only", "mixed", "tracking_advance"):
            result = scenarios[scenario][phase]["p95"]
            if result["financial_parquet_scans"] == 0:
                raise AssertionError(f"{scenario} benchmark did not read its Financial partition")
            if result["raw_financial_batch_opens"] != 0:
                raise AssertionError(f"{scenario} benchmark reopened Raw Financial Batches")


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


if __name__ == "__main__":
    main()
