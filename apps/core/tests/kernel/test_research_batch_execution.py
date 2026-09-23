from __future__ import annotations

import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from thesistrace.alpha_language import alpha_language
from thesistrace.data import MountedGenerationStore
from thesistrace.fixture import build_fixture
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_batch.execution import execute_research_batch_messages
from thesistrace.research_definition import default_simulation_costs
from thesistrace.research_kernel.numeric import NUMERIC_CONTRACT_ID
from thesistrace.research_run.models import (
    DataAdmissionFacts,
    ExpressionAdmissionFacts,
    ImmutableRunInput,
)
from thesistrace.research_run.planning import plan_research_chunks
from thesistrace.research_run.service import (
    FIXED_EXECUTION,
    FIXED_STRATEGY_KIND,
    SEMANTIC_VERSIONS,
)


@pytest.mark.parametrize("reuse_private_artifact", (False, True))
def test_strategy_sweep_needs_no_alpha_source_columns_after_shared_calculation(
    tmp_path: Path,
    monkeypatch,
    reuse_private_artifact: bool,
) -> None:
    from thesistrace.research_batch import execution

    def forbidden_labels(*_args, **_kwargs):
        raise AssertionError("Strategy Batch must not prepare future labels")

    monkeypatch.setattr(execution, "prepare_columnar_forward_labels", forbidden_labels)
    request = _batch_request(tmp_path, kind="strategy_sweep")
    reference = list(execute_research_batch_messages(request))
    expected = _completed_chunks(reference)
    assert len(expected) == 3, reference

    artifact = tmp_path / "strategy-only.alpha-factor"
    if reuse_private_artifact:
        shutil.copyfile(request["private_artifact_path"], artifact)
    request = {
        **request,
        "private_artifact_path": str(artifact),
        "reuse_private_artifact": reuse_private_artifact,
    }
    # Enforce the storage boundary: execution prices remain available, while
    # Alpha-only column decoding is unavailable once the reusable result exists.
    alpha_complete = reuse_private_artifact
    iter_batches = pq.ParquetFile.iter_batches

    def execution_columns_only(parquet, *args, columns=None, **kwargs):
        if alpha_complete:
            selected = set(parquet.schema_arrow.names if columns is None else columns)
            if "volume_shares" in selected or "sw2021_l1" in selected:
                raise OSError("Alpha source columns are unavailable during Strategy execution")
        return iter_batches(parquet, *args, columns=columns, **kwargs)

    monkeypatch.setattr(pq.ParquetFile, "iter_batches", execution_columns_only)
    messages = []
    for message in execute_research_batch_messages(request):
        messages.append(message)
        if message["status"] == "shared_alpha_factor_succeeded":
            alpha_complete = True

    actual = _completed_chunks(messages)
    assert len(actual) == 3, messages
    for reference_chunk, chunk in zip(expected, actual, strict=True):
        assert canonical_json_bytes(chunk["final_values"]) == canonical_json_bytes(
            reference_chunk["final_values"]
        )
        assert canonical_json_bytes(chunk["continuation"]) == canonical_json_bytes(
            reference_chunk["continuation"]
        )
    expected_daily = [
        pq.read_table(message["strategy_partition"]["path"]).to_pylist()
        for message in reference
        if message["status"] == "item_strategy_chunk_succeeded"
    ]
    actual_daily = [
        pq.read_table(message["strategy_partition"]["path"]).to_pylist()
        for message in messages
        if message["status"] == "item_strategy_chunk_succeeded"
    ]
    assert canonical_json_bytes(actual_daily) == canonical_json_bytes(expected_daily)


def test_factor_batch_reports_measured_calculation_phases(tmp_path: Path) -> None:
    messages = list(
        execute_research_batch_messages(_batch_request(tmp_path, kind="factor_evaluation"))
    )
    completed = _completed_chunks(messages)
    assert len(completed) == 3, messages
    for message in messages:
        if message["status"] != "item_chunk_succeeded":
            continue
        phases = message["child_calculation_phase_seconds"]
        assert phases["input"] > 0
        assert phases["alpha_and_pending"] > 0
        assert phases["factor"] > 0
        assert phases["strategy"] == 0
        if message["chunk"]["final"]:
            assert phases["finalize"] > 0
        assert sum(phases.values()) <= message["child_chunk_seconds"]


def _completed_chunks(messages):
    return [
        message["chunk"]
        for message in messages
        if message["status"] in {"item_chunk_succeeded", "item_succeeded"}
        and message["chunk"]["final"]
    ]


def test_strategy_sweep_shares_alpha_with_distinct_costs_per_item(tmp_path):
    request = _batch_request(tmp_path, kind="strategy_sweep")
    for ordinal, item in enumerate(request["items"], start=1):
        item["immutable_input"]["costs"].update(
            commission_min_cny=str(ordinal), slippage_bps=str(ordinal * 10),
        )
    messages = list(execute_research_batch_messages(request))
    assert any(
        message["status"] == "shared_alpha_factor_succeeded" for message in messages
    ), messages
    assert len(_completed_chunks(messages)) == 3, messages


def _batch_request(
    tmp_path: Path, *, kind: str, daily_fields: bool = False,
    formula: str = "rank(ts_mean(volume, 30))",
) -> dict[str, object]:
    _, canonical = build_fixture(session_count=100)
    if daily_fields:
        from thesistrace.data.canonical_mapping import daily_basic_field_catalog, field_catalog
        from thesistrace.data.fields import DAILY_BASIC_FIELDS

        calendar = canonical["research_calendar"]
        canonical["daily_basic_sessions"] = [{"session": session} for session in calendar]
        canonical["daily_basic"] = [{
            **dict.fromkeys(field.source_column for field in DAILY_BASIC_FIELDS),
            "session": price["session"], "instrument_id": price["instrument_id"],
            "source_close": "999", "pe": str(10 + index % 7), "turnover_rate": "0.025",
        } for index, price in enumerate(canonical["prices"]) if price["session"] != calendar[60]]
        canonical["field_catalog"] = [
            *field_catalog(calendar[-1]), *daily_basic_field_catalog(calendar[-1]),
        ]
    store = MountedGenerationStore(tmp_path / "data")
    generation = store.materialize(
        canonical,
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )
    sessions = tuple(date.fromisoformat(value) for value in canonical["research_calendar"])
    compiled = alpha_language.compile(
        "rank(close_raw / pe + turnover_rate)" if daily_fields else formula
    )
    offset = max(21, compiled.effective_lookback)
    plan = plan_research_chunks(
        calculation_sessions=sessions,
        research_session_offset=offset,
        formula_work=compiled.estimated_work,
        node_count=compiled.node_count,
        field_count=len(compiled.field_ids_by_identifier),
        maximum_universe_cardinality=len(canonical["instruments"]),
        effective_lookback=compiled.effective_lookback,
        execution_memory_bytes=1536 * 1024**2,
    )
    assert plan.research_session_count > plan.chunk_session_count
    strategy = kind == "strategy_sweep"
    items = []
    for ordinal, (holdings, rebalance) in enumerate(((1, 1), (2, 3), (3, 5)), start=1):
        immutable = ImmutableRunInput(
            formula_source=compiled.source,
            alpha_expression=compiled.expression,
            hypothesis=None,
            requested_start_date=sessions[offset],
            requested_end_date=sessions[-1],
            field_bindings={value: key for key, value in compiled.field_ids_by_identifier.items()},
            universe="top300",
            neutralization="industry",
            research_kind="strategy_backtest" if strategy else "factor_evaluation",
            strategy={"volatility_window": 20, "weighting": "equal_weight",
                "kind": FIXED_STRATEGY_KIND,
                "modules": {
                    "universe_selection": "dataset_universe/v1", "alpha": "alpha_formula/v1",
                    "portfolio_construction": "periodic_top_n/v1", "risk_management": "no_risk/v1",
                },
                "holdings_count": holdings,
                "selection_every_sessions": rebalance,
                "initial_cash_cny": "10000000",
                "execution": FIXED_EXECUTION,
                "exposure_source": "1",
                "exposure_expression": {"kind": "number", "value": 1},
            }
            if strategy
            else None,
            costs=default_simulation_costs().model_dump() if strategy else None,
            risk_free_rate="0" if strategy else None,
            numeric_execution_contract=NUMERIC_CONTRACT_ID,
            semantic_versions=SEMANTIC_VERSIONS,
            expression_admission=ExpressionAdmissionFacts(
                effective_lookback=compiled.effective_lookback,
                node_count=compiled.node_count,
                depth=compiled.depth,
                formula_work=compiled.estimated_work,
                estimated_run_work=compiled.estimated_work * len(sessions),
            ),
            data_admission=DataAdmissionFacts(
                generation_manifest_sha256=generation.manifest_sha256,
                data_through_session=sessions[-1],
                coverage_start=sessions[0],
                coverage_end=sessions[-1],
                first_research_session=sessions[offset],
                last_research_session=sessions[-1],
                calculation_session_count=len(sessions),
                universe_instrument_count=len(canonical["instruments"]),
                financial_research_readiness="not_ready",
            ),
            execution_plan=plan,
        )
        items.append(
            {
                "ordinal": ordinal,
                "item_key": f"item-{ordinal}",
                "run_id": f"run-{ordinal}",
                "immutable_input": immutable.canonical_value(),
            }
        )
    return {
        "schema_version": "research-batch-child-request-v2",
        "batch_kind": kind,
        "batch_id": "batch-projected-input",
        "data_mount": str(tmp_path / "data"),
        "data_generation_id": generation.manifest_sha256,
        "items": items,
        "private_artifact_path": str(tmp_path / "reference.alpha-factor") if strategy else None,
        "reuse_private_artifact": False,
    }


@pytest.mark.parametrize("kind", ["factor_evaluation", "strategy_sweep"])
def test_batch_streams_common_statistics_for_every_item_and_research_session(tmp_path, kind):
    request = _batch_request(
        tmp_path,
        kind=kind,
        formula="rank(ts_mean(close, 30)) * universe_advancing_fraction()",
    )
    messages = list(execute_research_batch_messages(request))
    assert len(_completed_chunks(messages)) == 3, messages
    streams = {ordinal: [] for ordinal in (1, 2, 3)}
    for message in messages:
        if message["status"] == "item_common_input_chunk_succeeded":
            streams[message["item_ordinal"]].extend(message["common_input_observations"])
    first = streams[1]
    assert first
    assert streams[2] == first == streams[3]
    immutable = request["items"][0]["immutable_input"]
    assert len(first) == immutable["execution_plan"]["research_session_count"]
    assert first[0]["session"] == immutable["data_admission"]["first_research_session"]
    assert first[-1]["session"] == immutable["data_admission"]["last_research_session"]
    assert all(row["identifier"] == "universe_advancing_fraction" for row in first)


def test_factor_batch_streams_daily_evidence_for_each_item_and_horizon(tmp_path):
    request = _batch_request(tmp_path, kind="factor_evaluation")
    messages = list(execute_research_batch_messages(request))
    streams = {ordinal: [] for ordinal in (1, 2, 3)}
    for message in messages:
        if message["status"] == "item_factor_evidence_succeeded":
            streams[message["item_ordinal"]].extend(message["factor_daily_observations"])
    for ordinal, rows in streams.items():
        assert rows, (ordinal, messages)
        sessions = {
            h: [row["session"] for row in rows if row["horizon"] == h]
            for h in (1, 5, 20)
        }
        assert sessions[1] == sessions[5] == sessions[20]
        assert sessions[1] == sorted(set(sessions[1]))
        assert all(
            [row for row in rows if row["horizon"] == h][-1]["label_exit_session"] is None
            for h in (1, 5, 20)
        )


@pytest.mark.parametrize("kind", ("factor_evaluation", "strategy_sweep"))
def test_daily_field_batch_matches_single_research_execution(tmp_path, monkeypatch, kind) -> None:
    from thesistrace.adapters.tushare_provider import TushareAdapter
    from thesistrace.research_run.execution import execute_request_chunks

    request = _batch_request(tmp_path, kind=kind, daily_fields=True)

    def reject_source(*_args, **_kwargs):
        raise AssertionError("Research cannot fetch supplier data")

    monkeypatch.setattr(TushareAdapter, "query_raw", reject_source)
    messages = list(execute_research_batch_messages(request))
    completed = _completed_chunks(messages)
    assert len(completed) == 3, messages
    for item, batch_chunk in zip(request["items"], completed, strict=True):
        single_messages = list(execute_request_chunks({
            "schema_version": "research-child-request-v1",
            "data_mount": request["data_mount"],
            "data_generation_id": request["data_generation_id"],
            "immutable_input": item["immutable_input"],
        }, cancel_requested=lambda: False))
        assert all(message["status"] == "chunk_succeeded" for message in single_messages)
        single_chunk = single_messages[-1]["chunk"]
        assert single_chunk["final"]
        assert single_chunk["final_values"] == batch_chunk["final_values"]
        assert single_chunk["continuation"] == batch_chunk["continuation"]
