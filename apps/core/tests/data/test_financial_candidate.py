from __future__ import annotations

import gc
import hashlib
import json
import tracemalloc
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from thesistrace.data.financial_candidate import (
    FinancialCandidateError,
    FinancialCandidateStore,
    FinancialDiscoveryPublication,
    FinancialSourceObservation,
    FinancialVersionProjector,
)
from thesistrace.data.financial_collection import (
    FINANCIAL_ENDPOINTS,
    CompletedFinancialCollection,
    FinancialCollectionContract,
    FinancialDateShard,
    FinancialShardCheckpoint,
    RawFinancialBatchStore,
)
from thesistrace.data.financial_series import FinancialSeriesResolver
from thesistrace.data.generation_files import AddressedFileStore
from thesistrace.data.generation_store import GenerationFileRef, MountedGenerationStore
from thesistrace.data.io_metrics import measure_data_io
from thesistrace.fixture import build_minimal_canonical_fixture
from thesistrace.publication.serialization import canonical_json_bytes

SESSIONS = (
    "2008-04-28",
    "2009-04-27",
    "2010-01-04",
    "2010-04-20",
    "2010-04-21",
    "2010-04-22",
    "2026-04-27",
    "2026-08-13",
)
FIELDS = (
    "ts_code",
    "ann_date",
    "f_ann_date",
    "end_date",
    "report_type",
    "comp_type",
    "end_type",
    "revenue",
    "update_flag",
)
FULL_EXECUTABLE_FIELDS = (
    *FIELDS,
    "total_revenue",
    "n_income_attr_p",
    "n_cashflow_act",
    "total_assets",
    "total_liab",
    "total_hldr_eqy_exc_min_int",
    "money_cap",
    "accounts_receiv",
    "notes_receiv",
    "oth_receiv",
    "prepayment",
    "inventories",
    "acct_payable",
    "contract_assets",
    "contract_liab",
    "goodwill",
    "st_borr",
    "lt_borr",
    "bond_payable",
    "non_cur_liab_due_1y",
    "oth_eqt_tools",
    "c_cash_equ_end_period",
)


def _materialized_candidate(
    tmp_path: Path, *, extra_income_versions: int = 0, quarterly_cash_seed: bool = False,
):
    market_manifest = _market_generation(tmp_path)
    batches = RawFinancialBatchStore(tmp_path)
    checkpoints: list[FinancialShardCheckpoint] = []

    def add_batch(
        ordinal: int,
        endpoint: str,
        items: list[list[object]],
        collected_at: datetime,
        *,
        shard: str,
        instrument_id: str = "equity:000001.SZ",
        ts_code: str = "000001.SZ",
    ) -> None:
        publication_dates = [str(item[2] or item[1]) for item in items if item[2] or item[1]]
        payload_sha256 = hashlib.sha256(
            canonical_json_bytes({"fields": list(FIELDS), "items": items})
        ).hexdigest()
        payload = {
            "format": "thesistrace-raw-financial-batch",
            "version": 1,
            "source_contract_version": "tushare-financial-ordinary-v2",
            "endpoint": endpoint,
            "parameters": {"ts_code": ts_code},
            "returned_fields": list(FIELDS),
            "items": items,
            "row_count": len(items),
            "source_date_extent": (
                None if not publication_dates else [min(publication_dates), max(publication_dates)]
            ),
            "payload_sha256": payload_sha256,
        }
        batch_sha256 = batches.store(canonical_json_bytes(payload))
        checkpoints.append(
            FinancialShardCheckpoint(
                ordinal=ordinal,
                endpoint=endpoint,
                instrument_id=instrument_id,
                ts_code=ts_code,
                shard=shard,
                status="completed",
                batch_sha256=batch_sha256,
                collected_at=collected_at.isoformat(),
                first_observed_at=collected_at.isoformat(),
            )
        )

    add_batch(
        0,
        "income",
        [
            ["000001.SZ", "20080425", "", "20071231", "1", "1", "4", "70", "0"],
            ["000001.SZ", "20090425", "", "20081231", "1", "1", "4", "80", "0"],
            ["000001.SZ", "20090425", "", "20081231", "1", "1", "4", "81", "1"],
            ["000001.SZ", "20091231", "", "20090930", "1", "1", "3", "90", "0"],
            ["000001.SZ", "20100420", "", "20091231", "1", "1", "4", None, "0"],
            ["000001.SZ", "20100420", "20100421", "20091231", "2", "2", "4", "200", "0"],
            ["000001.SZ", "20100420", "", "20091231", "1", "1", "4", "101", "1"],
            ["000001.SZ", "", "", "20100331", "1", "1", "1", "25", "0"],
            *[
                [
                    "000001.SZ",
                    "20100420",
                    "",
                    "20091231",
                    "1",
                    "1",
                    "4",
                    str(10000 + index),
                    "1",
                ]
                for index in range(extra_income_versions)
            ],
        ],
        datetime(2026, 4, 24, 8, tzinfo=UTC),
        shard="complete-history",
    )
    add_batch(
        1,
        "income",
        [["000002.SZ", "20090425", "", "20081231", "1", "1", "4", "900", "0"]],
        datetime(2026, 4, 24, 8, tzinfo=UTC),
        shard="complete-history",
        instrument_id="equity:000002.SZ",
        ts_code="000002.SZ",
    )
    add_batch(
        2,
        "balancesheet",
        [
            ["000001.SZ", "20090425", "", "20081231", "1", "1", "4", "500", "0"],
            ["000001.SZ", "20090425", "", "20081231", "1", "1", "4", "501", "1"],
            ["000001.SZ", "20260813", "", "20260630", "1", "1", "2", "999", "0"],
        ],
        datetime(2026, 4, 24, 8, tzinfo=UTC),
        shard="complete-history",
    )
    add_batch(
        3,
        "balancesheet",
        [["000002.SZ", "20090425", "", "20081231", "1", "1", "4", "950", "0"]],
        datetime(2026, 4, 24, 8, tzinfo=UTC),
        shard="complete-history",
        instrument_id="equity:000002.SZ",
        ts_code="000002.SZ",
    )
    add_batch(
        4,
        "cashflow",
        [
            ["000001.SZ", "20090425", "", "20081231", "1", "1", "4", "30", "0"],
            *(
                [["000001.SZ", "20090425", "", "20090331", "1", "1", "1", "45", "0"]]
                if quarterly_cash_seed else []
            ),
        ],
        datetime(2026, 4, 24, 8, tzinfo=UTC),
        shard="complete-history",
    )
    add_batch(
        5,
        "cashflow",
        [["000002.SZ", "20090425", "", "20081231", "1", "1", "4", "930", "0"]],
        datetime(2026, 4, 24, 8, tzinfo=UTC),
        shard="complete-history",
        instrument_id="equity:000002.SZ",
        ts_code="000002.SZ",
    )
    contract = FinancialCollectionContract(
        capability_sha256="b" * 64,
        endpoint_fields=tuple((endpoint, FIELDS) for endpoint in FINANCIAL_ENDPOINTS),
        suspected_truncation_row_counts=tuple((endpoint, None) for endpoint in FINANCIAL_ENDPOINTS),
        shards=(FinancialDateShard("complete-history"),),
    )
    snapshot = CompletedFinancialCollection(
        idempotency_key="financial-bootstrap",
        generation_manifest_sha256=market_manifest,
        contract=contract,
        finished_at=datetime(2026, 8, 13, 9, tzinfo=UTC).isoformat(),
        target_count=6,
        shards=tuple(checkpoints),
    )

    store = FinancialCandidateStore(tmp_path)
    first = store.materialize(
        snapshot,
        observation_through_session="2026-08-13",
    )
    repeated = store.materialize(
        snapshot,
        observation_through_session="2026-08-13",
    )

    return store, first, repeated, snapshot


def _targeted_instrument_collection(
    snapshot: CompletedFinancialCollection,
    *,
    idempotency_key: str,
    generation_manifest_sha256: str | None = None,
) -> CompletedFinancialCollection:
    checkpoints = tuple(
        replace(checkpoint, ordinal=ordinal)
        for ordinal, checkpoint in enumerate(
            item
            for item in snapshot.shards
            if item.instrument_id == "equity:000001.SZ"
        )
    )
    return replace(
        snapshot,
        idempotency_key=idempotency_key,
        generation_manifest_sha256=(
            snapshot.generation_manifest_sha256
            if generation_manifest_sha256 is None
            else generation_manifest_sha256
        ),
        target_count=len(checkpoints),
        shards=checkpoints,
    )


def _append_targeted_source_row(
    root: Path,
    collection: CompletedFinancialCollection,
    *,
    endpoint: str,
    row: list[object],
) -> CompletedFinancialCollection:
    raw = RawFinancialBatchStore(root)
    checkpoints: list[FinancialShardCheckpoint] = []
    for checkpoint in collection.shards:
        assert checkpoint.batch_sha256 is not None
        payload = raw.read(checkpoint.batch_sha256)
        items = [*payload["items"]]
        if checkpoint.endpoint == endpoint:
            items.append(row)
        publication_dates = [
            str(item[2] or item[1]) for item in items if item[2] or item[1]
        ]
        payload["items"] = items
        payload["row_count"] = len(items)
        payload["source_date_extent"] = [
            min(publication_dates),
            max(publication_dates),
        ]
        payload["payload_sha256"] = hashlib.sha256(
            canonical_json_bytes({"fields": list(FIELDS), "items": items})
        ).hexdigest()
        checkpoints.append(
            replace(
                checkpoint,
                ordinal=len(checkpoints),
                batch_sha256=raw.store(canonical_json_bytes(payload)),
                collected_at="2026-08-14T08:30:00+00:00",
                first_observed_at="2026-08-14T08:30:00+00:00",
            )
        )
    return replace(
        collection,
        finished_at="2026-08-14T09:00:00+00:00",
        shards=tuple(checkpoints),
    )


def test_materializes_sparse_versioned_financial_family_without_publishing(tmp_path: Path) -> None:
    store, first, repeated, _snapshot = _materialized_candidate(tmp_path)

    assert first == repeated == store.reopen(first.manifest_sha256)
    assert store.validate(first.manifest_sha256) == first
    assert first.family_id == "equity.financial_pit"
    assert first.coverage_start == "2010-01-04"
    assert first.observation_through_session == "2026-08-13"
    assert first.revision_coverage == "source-dated-and-first-observed-corrections"
    assert first.raw_batch_count == 6
    income = store.read_table(first.manifest_sha256, "income_statement_versions")
    available = [row for row in income if row["availability_status"] == "available"]
    quarantined = [row for row in income if row["availability_status"] == "quarantined"]
    assert {row["revenue"] for row in available} == {"70", "90", "200"}
    assert {row["revenue"] for row in quarantined} == {"25", "80", "81", "101", None}
    assert {row["revision_basis"] for row in income} == {"source_version"}
    by_value = {row["revenue"]: row for row in income}
    assert by_value["70"]["coverage_role"] == "pre_start_seed"
    assert by_value["70"]["effective_available_session"] == "2008-04-28"
    assert by_value["90"]["coverage_role"] == "in_coverage"
    assert by_value["90"]["effective_available_session"] == "2010-01-04"
    assert by_value["200"]["source_published_date"] == "20100421"
    assert by_value["200"]["effective_available_session"] == "2010-04-22"
    assert by_value["200"]["source_report_type"] == "2"
    assert by_value["200"]["source_company_type"] == "2"
    assert all(row["effective_available_session"] == "" for row in quarantined)
    assert all(row["coverage_role"] == "quarantined" for row in quarantined)
    assert by_value["25"]["source_available_session"] == ""
    assert by_value["101"]["source_available_session"] == "2010-04-21"
    assert by_value["101"]["source_row_sha256"] != by_value[None]["source_row_sha256"]
    assert by_value["101"]["logical_revision_group_sha256"] == (
        by_value[None]["logical_revision_group_sha256"]
    )
    assert by_value["101"]["source_batch_sha256"] == by_value[None]["source_batch_sha256"]
    # Income has four conflicting observations plus one undated observation;
    # balance sheet has another two conflicting observations. All remain evidence.
    assert store.quarantined_row_count(first.manifest_sha256) == 7
    balance = store.read_table(first.manifest_sha256, "balance_sheet_versions")
    pending_balance = [row for row in balance if row["availability_status"] == "pending_calendar"]
    assert {row["revenue"] for row in pending_balance} == {"999"}
    assert not (tmp_path / "HEAD.json").exists()


def test_materialization_does_not_retain_all_raw_batches(tmp_path: Path) -> None:
    _store, _first, _repeated, snapshot = _materialized_candidate(tmp_path)

    class TrackedBatch(dict[str, object]):
        live = 0
        peak = 0

        def __init__(self, value: dict[str, object]) -> None:
            super().__init__(value)
            type(self).live += 1
            type(self).peak = max(type(self).peak, type(self).live)

        def __del__(self) -> None:
            type(self).live -= 1

    class TrackingStore(FinancialCandidateStore):
        def _read_raw_batch(self, batch_sha256: str) -> dict[str, object]:
            return TrackedBatch(super()._read_raw_batch(batch_sha256))

    candidate = TrackingStore(tmp_path).materialize(
        snapshot,
        observation_through_session="2026-08-13",
    )
    gc.collect()

    assert candidate.raw_batch_count == 6
    assert TrackedBatch.live == 0
    assert TrackedBatch.peak <= 2


def test_validation_does_not_open_whole_financial_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, candidate, _repeated, _snapshot = _materialized_candidate(tmp_path)

    def reject_whole_table_open(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("validation must compare bounded table objects")

    monkeypatch.setattr(store, "_open_table", reject_whole_table_open)

    assert store.validate(candidate.manifest_sha256) == candidate


def test_only_a_complete_financial_candidate_can_form_a_composite_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_store, incomplete, _repeated, _snapshot = _materialized_candidate(tmp_path)
    market_manifest = candidate_store.source_generation_manifest_sha256(
        incomplete.manifest_sha256
    )
    generation_store = MountedGenerationStore(tmp_path)

    with pytest.raises(RuntimeError, match="incompatible"):
        generation_store.compose_financial_candidate(
            market_manifest,
            incomplete.manifest_sha256,
            prepared_at=datetime(2026, 8, 13, 10, tzinfo=UTC),
        )

    complete = candidate_store.materialize(
        _empty_complete_snapshot(
            tmp_path,
            market_manifest,
            idempotency_key="complete-financial-fields",
            fields=FULL_EXECUTABLE_FIELDS,
        ),
        observation_through_session="2026-08-13",
    )
    composite = generation_store.compose_financial_candidate(
        market_manifest,
        complete.manifest_sha256,
        prepared_at=datetime(2026, 8, 13, 10, tzinfo=UTC),
        publication_coordinate="a" * 64,
    )
    same_data_other_publication = generation_store.compose_financial_candidate(
        market_manifest,
        complete.manifest_sha256,
        prepared_at=datetime(2026, 8, 13, 11, tzinfo=UTC),
        publication_coordinate="b" * 64,
    )

    assert composite.financial_candidate_manifest_sha256 == complete.manifest_sha256
    assert composite.manifest_sha256 != same_data_other_publication.manifest_sha256
    assert composite.data_identity == same_data_other_publication.data_identity
    assert composite.financial_publication_coordinate == "a" * 64
    assert same_data_other_publication.financial_publication_coordinate == "b" * 64
    assert composite.families[-1].family_id == "equity.financial_pit"
    assert composite.families[-1].manifest_sha256 == complete.manifest_sha256
    assert {
        "financial.income.total_revenue.latest_fy",
        "financial.income.net_profit_parent.latest_fy",
        "financial.cashflow.operating_cash_flow.latest_fy",
        "financial.balance_sheet.total_assets.latest_reported",
        "financial.balance_sheet.total_liabilities.latest_reported",
        "financial.balance_sheet.equity_parent.latest_reported",
    } <= set(composite.field_availability)
    def reject_child_manifest(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("admission opened the child Financial manifest")

    monkeypatch.setattr(FinancialCandidateStore, "reopen", reject_child_manifest)
    admission = generation_store.open_admission(composite.manifest_sha256)
    assert admission.financial_observation_through_session == "2026-08-13"
    resolved = generation_store.read_composite_slice(
        composite.manifest_sha256,
        sessions=["2026-08-13"],
        universe_name="top300",
        neutralization="none",
        field_bindings={
            "financial.income.total_revenue.latest_fy": "revenue"
        },
    )
    assert resolved.research_data.fields == {
        "financial.income.total_revenue.latest_fy": {}
    }
    retained = generation_store.referenced_files(composite.manifest_sha256)
    assert retained <= generation_store.inventory()
    assert (
        sum(reference.kind == "raw_financial" for reference in retained)
        == complete.raw_batch_count
    )
    assert any(
        reference.kind == "manifest" and reference.sha256 == complete.manifest_sha256
        for reference in retained
    )

    root_path = (
        tmp_path
        / "manifests"
        / "sha256"
        / composite.manifest_sha256[:2]
        / f"{composite.manifest_sha256}.json"
    )
    forged = json.loads(root_path.read_bytes())
    forged["families"][-1]["validation_summary"]["row_count"] += 1
    identity = {
        key: forged[key]
        for key in (
            "schema_contract",
            "data_through_session",
            "research_sessions",
                "field_availability",
                "families",
                "financial_research_readiness",
            )
    }
    forged["data_identity"] = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    forged_content = canonical_json_bytes(forged)
    forged_sha256 = hashlib.sha256(forged_content).hexdigest()
    forged_path = (
        tmp_path / "manifests" / "sha256" / forged_sha256[:2] / f"{forged_sha256}.json"
    )
    AddressedFileStore(tmp_path).store(forged_path, forged_sha256, forged_content)

    with pytest.raises(RuntimeError, match="does not match its manifest"):
        generation_store.validate_generation(forged_sha256)


def test_market_refresh_reuses_previously_validated_financial_family(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_manifest = _market_generation(tmp_path)
    candidate_store = FinancialCandidateStore(tmp_path)
    complete = candidate_store.materialize(
        _empty_complete_snapshot(
            tmp_path,
            market_manifest,
            idempotency_key="validated-financial-family",
            fields=FULL_EXECUTABLE_FIELDS,
        ),
        observation_through_session="2026-08-13",
    )
    generation_store = MountedGenerationStore(tmp_path)
    composite = generation_store.compose_financial_candidate(
        market_manifest,
        complete.manifest_sha256,
        prepared_at=datetime(2026, 8, 13, 10, tzinfo=UTC),
    )
    refresh_base = generation_store.open_refresh_base(composite.manifest_sha256)

    def reject_revalidation(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("market refresh revalidated an immutable Financial Family")

    monkeypatch.setattr(FinancialCandidateStore, "validate", reject_revalidation)

    refreshed = generation_store.materialize_refresh(
        predecessor_manifest_sha256=composite.manifest_sha256,
        replacement_canonical=refresh_base.canonical,
        replace_from_session=str(refresh_base.canonical["research_calendar"][-3]),
        prepared_at=datetime(2026, 8, 14, 10, tzinfo=UTC),
        source_name="market-refresh",
        source_lineage={"snapshot": "next-market"},
    )

    assert refreshed.financial_candidate_manifest_sha256 == complete.manifest_sha256


def test_financial_generation_rejects_an_incomplete_research_readiness_slice(
    tmp_path: Path,
) -> None:
    candidate_store, _incomplete, _repeated, _snapshot = _materialized_candidate(tmp_path)
    market_manifest = candidate_store.source_generation_manifest_sha256(
        _incomplete.manifest_sha256
    )
    complete = candidate_store.materialize(
        _empty_complete_snapshot(
            tmp_path,
            market_manifest,
            idempotency_key="readiness-six-fields",
            fields=FULL_EXECUTABLE_FIELDS,
        ),
        observation_through_session="2026-08-13",
    )
    generation = MountedGenerationStore(tmp_path).compose_financial_candidate(
        market_manifest,
        complete.manifest_sha256,
        prepared_at=datetime(2026, 8, 13, 10, tzinfo=UTC),
    )
    root_path = (
        tmp_path
        / "manifests"
        / "sha256"
        / generation.manifest_sha256[:2]
        / f"{generation.manifest_sha256}.json"
    )
    root = json.loads(root_path.read_bytes())
    root["financial_research_readiness"]["daily_track"] = "missing"
    identity = {
        key: root[key]
        for key in (
            "schema_contract",
            "data_through_session",
            "research_sessions",
            "field_availability",
            "families",
            "financial_research_readiness",
        )
    }
    root["data_identity"] = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    content = canonical_json_bytes(root)
    sha256 = hashlib.sha256(content).hexdigest()
    path = tmp_path / "manifests" / "sha256" / sha256[:2] / f"{sha256}.json"
    AddressedFileStore(tmp_path).store(path, sha256, content)

    with pytest.raises(RuntimeError, match="Financial Research Readiness"):
        MountedGenerationStore(tmp_path).validate_generation(sha256)


def test_financial_generation_reopens_the_immutable_bootstrap_readiness_contract(
    tmp_path: Path,
) -> None:
    candidate_store, _incomplete, _repeated, _snapshot = _materialized_candidate(tmp_path)
    market_manifest = candidate_store.source_generation_manifest_sha256(
        _incomplete.manifest_sha256
    )
    complete = candidate_store.materialize(
        _empty_complete_snapshot(
            tmp_path,
            market_manifest,
            idempotency_key="immutable-bootstrap-readiness",
            fields=FULL_EXECUTABLE_FIELDS,
        ),
        observation_through_session="2026-08-13",
    )
    generation_store = MountedGenerationStore(tmp_path)
    generation = generation_store.compose_financial_candidate(
        market_manifest,
        complete.manifest_sha256,
        prepared_at=datetime(2026, 8, 13, 10, tzinfo=UTC),
    )
    root_path = (
        tmp_path
        / "manifests"
        / "sha256"
        / generation.manifest_sha256[:2]
        / f"{generation.manifest_sha256}.json"
    )
    root = json.loads(root_path.read_bytes())
    readiness = root["financial_research_readiness"]
    for daily_key in (
        "attempted_through_session",
        "complete_through_session",
        "pending_instrument_count",
        "discovery_gap_count",
        "earliest_unresolved_date",
    ):
        readiness.pop(daily_key, None)
    identity = {
        key: root[key]
        for key in (
            "schema_contract",
            "data_through_session",
            "research_sessions",
            "field_availability",
            "families",
            "financial_research_readiness",
        )
    }
    root["data_identity"] = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    content = canonical_json_bytes(root)
    sha256 = hashlib.sha256(content).hexdigest()
    path = tmp_path / "manifests" / "sha256" / sha256[:2] / f"{sha256}.json"
    AddressedFileStore(tmp_path).store(path, sha256, content)

    reopened = generation_store.validate_generation(sha256)

    assert reopened.financial_research_readiness == readiness
    assert generation_store.open_admission(sha256).financial_research_readiness == "ready"


def test_financial_series_read_projects_requested_columns_and_instruments(
    tmp_path: Path,
) -> None:
    store, candidate, _repeated, _snapshot = _materialized_candidate(tmp_path)

    rows = store.read_financial_rows(
        candidate.manifest_sha256,
        "income",
        ("instrument_id", "effective_available_session", "revenue"),
        ("2010-01-04", "2010-04-21", "2026-08-13"),
        frozenset({"equity:000001.SZ"}),
    )

    assert rows
    assert all(
        set(row) == {"instrument_id", "effective_available_session", "revenue"} for row in rows
    )
    assert {row["instrument_id"] for row in rows} == {"equity:000001.SZ"}
    with pytest.raises(FinancialCandidateError, match="FINANCIAL_SERIES_SESSION_INVALID"):
        store.read_financial_rows(
            candidate.manifest_sha256,
            "income",
            ("instrument_id", "effective_available_session", "revenue"),
            ("2010-01-05",),
            frozenset({"equity:000001.SZ"}),
        )
    with pytest.raises(FinancialCandidateError, match="FINANCIAL_SERIES_COVERAGE_INVALID"):
        store.read_financial_rows(
            candidate.manifest_sha256,
            "income",
            ("instrument_id", "effective_available_session", "revenue"),
            ("2009-04-27", "2010-01-04"),
            frozenset({"equity:000001.SZ"}),
        )


def test_financial_table_read_keeps_python_memory_bounded(tmp_path: Path) -> None:
    store, candidate, _repeated, _snapshot = _materialized_candidate(
        tmp_path, extra_income_versions=12000
    )
    # Arrow owns the data buffers. A projected read must not also retain a
    # Python string/dict representation of every historical version.
    gc.collect()
    tracemalloc.start()
    try:
        with measure_data_io() as measurement:
            table = store.read_financial_table(
                candidate.manifest_sha256,
                "income",
                ("instrument_id", "effective_available_session", "revenue"),
                ("2010-04-21", "2010-04-22"),
                frozenset({"equity:000001.SZ"}),
            )
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert measurement.rows_scanned >= 12000
    assert table.column_names == ["instrument_id", "effective_available_session", "revenue"]
    assert store.quarantined_row_count(candidate.manifest_sha256) >= 12000
    assert peak < 4 * 1024**2, f"Projected read allocated {peak} Python bytes"


def test_financial_series_read_compacts_superseded_pre_window_versions(tmp_path: Path) -> None:
    store, candidate, _repeated, _snapshot = _materialized_candidate(tmp_path)

    rows = store.read_financial_rows(
        candidate.manifest_sha256,
        "income",
        (
            "instrument_id",
            "source_report_period",
            "source_report_type",
            "source_company_type",
            "effective_available_session",
            "availability_status",
            "first_observed_at",
            "source_published_date",
            "source_row_sha256",
            "update_flag",
            "revenue",
        ),
        ("2026-04-27", "2026-08-13"),
        frozenset({"equity:000001.SZ"}),
    )

    available = [row for row in rows if row["availability_status"] == "available"]
    assert {row["revenue"] for row in available} == {"70", "90", "200"}
    assert len(available) == 3
    # Query compaction is a projection only: every quarantined original stays
    # in the immutable candidate, and none acquires an effective session.
    original = store.read_table(candidate.manifest_sha256, "income_statement_versions")
    quarantined = [row for row in original if row["availability_status"] == "quarantined"]
    assert {row["revenue"] for row in quarantined} == {"25", "80", "81", "101", None}
    assert all(row["effective_available_session"] == "" for row in quarantined)



@pytest.mark.parametrize("target", ["raw", "parquet"])
@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_missing_or_corrupt_financial_evidence_fails_closed(
    tmp_path: Path,
    target: str,
    damage: str,
) -> None:
    store, candidate, _repeated, snapshot = _materialized_candidate(tmp_path)
    if target == "raw":
        sha256 = str(snapshot.shards[0].batch_sha256)
        path = tmp_path / "financial" / "raw" / "sha256" / sha256[:2] / f"{sha256}.json"
        expected = "FINANCIAL_RAW_BATCH_INVALID"
    else:
        family_path = (
            tmp_path
            / "manifests"
            / "sha256"
            / candidate.manifest_sha256[:2]
            / f"{candidate.manifest_sha256}.json"
        )
        family = json.loads(family_path.read_bytes())
        table_sha256 = str(family["tables"][0]["manifest_sha256"])
        table_path = (
            tmp_path / "manifests" / "sha256" / table_sha256[:2] / f"{table_sha256}.json"
        )
        table = json.loads(table_path.read_bytes())
        sha256 = str(table["objects"][0]["sha256"])
        path = tmp_path / "objects" / "sha256" / sha256[:2] / f"{sha256}.parquet"
        expected = "FINANCIAL_ADDRESSED_FILE_INVALID"
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"corrupt")

    with pytest.raises(FinancialCandidateError, match=expected):
        store.validate(candidate.manifest_sha256)


def test_revalidation_rejects_self_consistent_false_coverage(tmp_path: Path) -> None:
    store, candidate, _repeated, _snapshot = _materialized_candidate(tmp_path)
    path = (
        tmp_path
        / "manifests"
        / "sha256"
        / candidate.manifest_sha256[:2]
        / f"{candidate.manifest_sha256}.json"
    )
    manifest = json.loads(path.read_bytes())
    manifest["dataset_coverage"]["expected_shard_count"] = 2
    content = canonical_json_bytes(manifest)
    forged_sha256 = hashlib.sha256(content).hexdigest()
    forged_path = tmp_path / "manifests" / "sha256" / forged_sha256[:2] / f"{forged_sha256}.json"
    AddressedFileStore(tmp_path).store(forged_path, forged_sha256, content)

    with pytest.raises(FinancialCandidateError, match="FINANCIAL_COVERAGE_INVALID"):
        store.validate(forged_sha256)


def test_materialization_rejects_incomplete_expected_shards(tmp_path: Path) -> None:
    store, _candidate, _repeated, snapshot = _materialized_candidate(tmp_path)
    incomplete = replace(snapshot, target_count=5, shards=snapshot.shards[:5])

    with pytest.raises(FinancialCandidateError, match="FINANCIAL_COLLECTION_TARGET_SET_INVALID"):
        store.materialize(incomplete, observation_through_session="2026-08-13")


def test_materialization_rejects_consistently_narrower_than_pinned_schema(
    tmp_path: Path,
) -> None:
    store, _candidate, _repeated, snapshot = _materialized_candidate(tmp_path)
    pinned = replace(
        snapshot.contract,
        endpoint_fields=tuple(
            (endpoint, (*fields, "ebit")) for endpoint, fields in snapshot.contract.endpoint_fields
        ),
    )

    with pytest.raises(FinancialCandidateError, match="FINANCIAL_SOURCE_SCHEMA_DRIFT"):
        store.materialize(
            replace(snapshot, contract=pinned),
            observation_through_session="2026-08-13",
        )
    missing_identity_field = replace(
        snapshot.contract,
        endpoint_fields=tuple(
            (endpoint, tuple(field for field in fields if field != "f_ann_date"))
            for endpoint, fields in snapshot.contract.endpoint_fields
        ),
    )
    with pytest.raises(FinancialCandidateError, match="FINANCIAL_SHARD_CONTRACT_INVALID"):
        store.materialize(
            replace(snapshot, contract=missing_identity_field),
            observation_through_session="2026-08-13",
        )


def test_materialization_rejects_wrong_instrument_identity_and_shard_parameters(
    tmp_path: Path,
) -> None:
    store, _candidate, _repeated, snapshot = _materialized_candidate(tmp_path)
    wrong_identity = replace(
        snapshot,
        shards=(replace(snapshot.shards[0], ts_code="000002.SZ"), *snapshot.shards[1:]),
    )
    with pytest.raises(FinancialCandidateError, match="FINANCIAL_COLLECTION_TARGET_SET_INVALID"):
        store.materialize(wrong_identity, observation_through_session="2026-08-13")

    first = snapshot.shards[0]
    assert first.batch_sha256 is not None
    raw = RawFinancialBatchStore(tmp_path)
    batch = raw.read(first.batch_sha256)
    batch["parameters"] = {
        "ts_code": first.ts_code,
        "start_date": "19900101",
        "end_date": "19901231",
    }
    forged_sha256 = raw.store(canonical_json_bytes(batch))
    with pytest.raises(FinancialCandidateError, match="FINANCIAL_SHARD_PARAMETERS_INVALID"):
        store.materialize(
            replace(
                snapshot,
                shards=(replace(first, batch_sha256=forged_sha256), *snapshot.shards[1:]),
            ),
            observation_through_session="2026-08-13",
        )


def test_materialization_rechecks_truncation_and_rejects_bounded_shards(
    tmp_path: Path,
) -> None:
    store, _candidate, _repeated, snapshot = _materialized_candidate(tmp_path)
    income_row_count = 7
    truncation = replace(
        snapshot.contract,
        suspected_truncation_row_counts=tuple(
            (endpoint, income_row_count if endpoint == "income" else None)
            for endpoint in FINANCIAL_ENDPOINTS
        ),
    )
    with pytest.raises(FinancialCandidateError, match="FINANCIAL_SUSPECTED_TRUNCATION"):
        store.materialize(
            replace(snapshot, contract=truncation),
            observation_through_session="2026-08-13",
        )

    bounded = replace(
        snapshot.contract,
        shards=(FinancialDateShard("bounded", "19900101", "20260812"),),
    )
    with pytest.raises(FinancialCandidateError, match="FINANCIAL_SHARD_CONTRACT_INVALID"):
        store.materialize(
            replace(snapshot, contract=bounded),
            observation_through_session="2026-08-13",
        )


def test_materialization_rejects_unproven_unbounded_and_oversized_shard_contracts(
    tmp_path: Path,
) -> None:
    store, _candidate, _repeated, snapshot = _materialized_candidate(tmp_path)
    multiple_unbounded = replace(
        snapshot.contract,
        shards=(FinancialDateShard("history-a"), FinancialDateShard("history-b")),
    )
    with pytest.raises(FinancialCandidateError, match="FINANCIAL_SHARD_CONTRACT_INVALID"):
        store.materialize(
            replace(snapshot, contract=multiple_unbounded),
            observation_through_session="2026-08-13",
        )
    oversized = replace(
        snapshot.contract,
        shards=(FinancialDateShard("oversized", "19900101", "19910102"),),
    )
    with pytest.raises(FinancialCandidateError, match="FINANCIAL_SHARD_CONTRACT_INVALID"):
        store.materialize(
            replace(snapshot, contract=oversized),
            observation_through_session="2026-08-13",
        )


def test_projector_classifies_later_pending_payload_as_observed_correction() -> None:
    payloads = (
        ("2026-08-13T08:00:00+00:00", "100", "a" * 64),
        ("2026-08-14T08:00:00+00:00", "101", "b" * 64),
    )
    observations = tuple(
        FinancialSourceObservation(
            endpoint="income",
            instrument_id="equity:000001.SZ",
            ts_code="000001.SZ",
            source_fields=FIELDS,
            source_values=(
                "000001.SZ",
                "20260813",
                "",
                "20260630",
                "1",
                "1",
                "2",
                revenue,
                "0",
            ),
            first_observed_at=observed_at,
            raw_batch_sha256=batch_sha256,
        )
        for observed_at, revenue, batch_sha256 in payloads
    )

    versions = FinancialVersionProjector().project(observations, SESSIONS)

    assert [version.availability_status for version in versions] == [
        "pending_calendar",
        "pending_calendar",
    ]
    assert [version.revision_basis for version in versions] == [
        "source_version",
        "observed_correction",
    ]


def test_projector_orders_mixed_offsets_and_uses_shanghai_session_date() -> None:
    observations = tuple(
        FinancialSourceObservation(
            endpoint="income",
            instrument_id="equity:000001.SZ",
            ts_code="000001.SZ",
            source_fields=FIELDS,
            source_values=(
                "000001.SZ",
                "20260811",
                "",
                "20260630",
                "1",
                "1",
                "2",
                revenue,
                "0",
            ),
            first_observed_at=observed_at,
            raw_batch_sha256=batch_sha256,
        )
        for observed_at, revenue, batch_sha256 in (
            ("2026-08-13T00:30:00+09:00", "100", "a" * 64),
            ("2026-08-12T16:00:00+00:00", "101", "b" * 64),
        )
    )

    versions = FinancialVersionProjector().project(
        observations,
        ("2026-08-12", "2026-08-13", "2026-08-14"),
    )

    assert [version.source()["revenue"] for version in versions] == ["100", "101"]
    assert [version.revision_basis for version in versions] == [
        "source_version",
        "observed_correction",
    ]
    assert versions[0].first_observed_at == "2026-08-12T15:30:00+00:00"
    assert versions[0].first_observed_session == "2026-08-13"
    assert versions[1].first_observed_at == "2026-08-12T16:00:00+00:00"
    assert versions[1].first_observed_session == "2026-08-14"
    assert versions[1].effective_available_session == "2026-08-14"


def test_candidate_validation_compares_collected_at_as_an_instant(tmp_path: Path) -> None:
    store, _candidate, _repeated, snapshot = _materialized_candidate(tmp_path)
    mixed_offset = replace(
        snapshot,
        finished_at="2026-08-13T02:00:00+00:00",
        shards=(
            replace(snapshot.shards[0], collected_at="2026-08-13T10:00:00+09:00"),
            *snapshot.shards[1:],
        ),
    )

    candidate = store.materialize(
        mixed_offset,
        observation_through_session="2026-08-13",
    )

    assert store.validate(candidate.manifest_sha256) == candidate


def test_rebuild_unions_prior_evidence_and_never_deletes_absent_versions(
    tmp_path: Path,
) -> None:
    store, prior, _repeated, snapshot = _materialized_candidate(tmp_path)
    raw = RawFinancialBatchStore(tmp_path)
    current_checkpoint = snapshot.shards[0]
    assert current_checkpoint.batch_sha256 is not None
    current_batch = raw.read(current_checkpoint.batch_sha256)
    current_items = [["000001.SZ", "20100420", "", "20091231", "1", "1", "4", "102", "1"]]
    current_batch["items"] = current_items
    current_batch["row_count"] = 1
    current_batch["source_date_extent"] = ["20100420", "20100420"]
    current_batch["payload_sha256"] = hashlib.sha256(
        canonical_json_bytes({"fields": list(FIELDS), "items": current_items})
    ).hexdigest()
    current_sha256 = raw.store(canonical_json_bytes(current_batch))
    refreshed = replace(
        snapshot,
        idempotency_key="financial-refresh",
        shards=(
            replace(
                current_checkpoint,
                batch_sha256=current_sha256,
                collected_at="2026-04-25T08:00:00+00:00",
                first_observed_at="2026-04-25T08:00:00+00:00",
            ),
            *snapshot.shards[1:],
        ),
    )

    candidate = store.rebuild(
        refreshed,
        prior_candidate_manifest_sha256=prior.manifest_sha256,
        observation_through_session="2026-08-13",
    )
    repeated = store.rebuild(
        refreshed,
        prior_candidate_manifest_sha256=prior.manifest_sha256,
        observation_through_session="2026-08-13",
    )

    assert candidate == repeated == store.validate(candidate.manifest_sha256)
    assert candidate.raw_batch_count == prior.raw_batch_count + 1
    income = store.read_table(candidate.manifest_sha256, "income_statement_versions")
    assert {row["revenue"] for row in income} >= {None, "25", "81", "90", "101", "102", "200"}
    correction = next(row for row in income if row["revenue"] == "102")
    assert correction["revision_basis"] == "observed_correction"
    assert correction["effective_available_session"] == "2026-04-27"
    assert not (tmp_path / "HEAD.json").exists()

    candidate_path = (
        tmp_path
        / "manifests"
        / "sha256"
        / candidate.manifest_sha256[:2]
        / f"{candidate.manifest_sha256}.json"
    )
    forged = json.loads(candidate_path.read_bytes())
    assert "prior_candidate_manifest_sha256" not in forged
    forged["raw_evidence"] = forged["current_raw_evidence"]
    forged["validation_summary"]["raw_batch_count"] = forged["raw_evidence"]["entry_count"]
    forged_content = canonical_json_bytes(forged)
    forged_sha256 = hashlib.sha256(forged_content).hexdigest()
    AddressedFileStore(tmp_path).store(
        tmp_path / "manifests" / "sha256" / forged_sha256[:2] / f"{forged_sha256}.json",
        forged_sha256,
        forged_content,
    )
    with pytest.raises(
        FinancialCandidateError,
        match="FINANCIAL_CANONICAL_PROJECTION_INVALID",
    ):
        store.validate(forged_sha256)


def test_preflight_checks_prior_references_without_deep_revalidation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, prior, _repeated, snapshot = _materialized_candidate(tmp_path)
    original_validate = store.validate

    def reject_redundant_prior_validation(manifest_sha256: str):
        if manifest_sha256 == prior.manifest_sha256:
            raise AssertionError("immutable prior candidate was deep revalidated")
        return original_validate(manifest_sha256)

    monkeypatch.setattr(store, "validate", reject_redundant_prior_validation)
    monkeypatch.setattr(
        store._market,
        "validate_generation",
        lambda _manifest_sha256: (_ for _ in ()).throw(
            AssertionError("financial preflight used full Generation validation")
        ),
    )

    store.preflight_rebuild(
        prior_candidate_manifest_sha256=prior.manifest_sha256,
        generation_manifest_sha256=snapshot.generation_manifest_sha256,
        contract=snapshot.contract,
        observation_through_session=prior.observation_through_session,
    )


def test_rebuild_checks_prior_references_without_deep_revalidation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, prior, _repeated, snapshot = _materialized_candidate(tmp_path)
    original_validate = store.validate
    validated: list[str] = []

    def record_validation(manifest_sha256: str):
        validated.append(manifest_sha256)
        if manifest_sha256 == prior.manifest_sha256:
            raise AssertionError("immutable prior candidate was deep revalidated")
        return original_validate(manifest_sha256)

    monkeypatch.setattr(store, "validate", record_validation)
    monkeypatch.setattr(
        store._market,
        "validate_generation",
        lambda _manifest_sha256: (_ for _ in ()).throw(
            AssertionError("financial rebuild used full Generation validation")
        ),
    )

    rebuilt = store.rebuild(
        replace(snapshot, idempotency_key="head-anchored-prior-rebuild"),
        prior_candidate_manifest_sha256=prior.manifest_sha256,
        observation_through_session=prior.observation_through_session,
    )
    assert rebuilt == prior
    assert validated == []


def test_rebuild_rejects_prior_evidence_missing_from_current_market_identity_map(
    tmp_path: Path,
) -> None:
    store, prior, _repeated, snapshot = _materialized_candidate(tmp_path)
    current_market = _market_generation(tmp_path, include_second=False)
    current_shards = tuple(
        replace(checkpoint, ordinal=ordinal)
        for ordinal, checkpoint in enumerate(
            checkpoint
            for checkpoint in snapshot.shards
            if checkpoint.instrument_id == "equity:000001.SZ"
        )
    )
    current = replace(
        snapshot,
        idempotency_key="financial-refresh-after-identity-removal",
        generation_manifest_sha256=current_market,
        target_count=len(current_shards),
        shards=current_shards,
    )

    with pytest.raises(FinancialCandidateError, match="FINANCIAL_HISTORICAL_IDENTITY_INVALID"):
        store.rebuild(
            current,
            prior_candidate_manifest_sha256=prior.manifest_sha256,
            observation_through_session="2026-08-13",
        )


def test_exact_refresh_reuses_prior_family_manifest(tmp_path: Path) -> None:
    store, prior, _repeated, snapshot = _materialized_candidate(tmp_path)
    inventory_before = MountedGenerationStore(tmp_path).inventory()

    replay = store.rebuild(
        replace(snapshot, idempotency_key="exact-refresh-replay"),
        prior_candidate_manifest_sha256=prior.manifest_sha256,
        observation_through_session=prior.observation_through_session,
    )

    assert replay == prior
    assert MountedGenerationStore(tmp_path).inventory() == inventory_before


def test_exact_refresh_reuses_prior_manifest_across_timestamp_offsets(tmp_path: Path) -> None:
    store, _prior, _repeated, snapshot = _materialized_candidate(tmp_path)
    prior_snapshot = replace(
        snapshot,
        idempotency_key="offset-prior",
        shards=tuple(
            replace(
                checkpoint,
                collected_at="2026-08-13T10:00:00+09:00",
                first_observed_at="2026-08-13T00:00:00+00:00",
            )
            for checkpoint in snapshot.shards
        ),
    )
    prior = store.materialize(
        prior_snapshot,
        observation_through_session="2026-08-13",
    )
    replay_snapshot = replace(
        snapshot,
        idempotency_key="offset-replay",
        shards=tuple(
            replace(
                checkpoint,
                collected_at="2026-08-13T02:00:00+00:00",
                first_observed_at="2026-08-13T00:00:00+00:00",
            )
            for checkpoint in snapshot.shards
        ),
    )

    replay = store.rebuild(
        replay_snapshot,
        prior_candidate_manifest_sha256=prior.manifest_sha256,
        observation_through_session="2026-08-13",
    )

    assert replay == prior


def test_refresh_rejects_contract_and_cutoff_regressions_without_head(tmp_path: Path) -> None:
    store, prior, _repeated, snapshot = _materialized_candidate(tmp_path)
    incompatible = replace(
        snapshot.contract,
        endpoint_fields=tuple(
            (endpoint, (*fields, "ebit")) for endpoint, fields in snapshot.contract.endpoint_fields
        ),
    )

    with pytest.raises(FinancialCandidateError, match="FINANCIAL_REFRESH_CONTRACT_MISMATCH"):
        store.rebuild(
            replace(snapshot, contract=incompatible),
            prior_candidate_manifest_sha256=prior.manifest_sha256,
            observation_through_session=prior.observation_through_session,
        )
    with pytest.raises(FinancialCandidateError, match="FINANCIAL_REFRESH_CUTOFF_REGRESSION"):
        store.rebuild(
            snapshot,
            prior_candidate_manifest_sha256=prior.manifest_sha256,
            observation_through_session="2010-04-22",
        )
    assert not (tmp_path / "HEAD.json").exists()


def test_complete_history_refresh_extends_cutoff(
    tmp_path: Path,
) -> None:
    market_manifest = _market_generation(tmp_path)
    store = FinancialCandidateStore(tmp_path)
    prior_snapshot = _empty_complete_snapshot(
        tmp_path,
        market_manifest,
        idempotency_key="complete-prior",
    )
    prior = store.materialize(
        prior_snapshot,
        observation_through_session="2026-04-27",
    )
    current_snapshot = _empty_complete_snapshot(
        tmp_path,
        market_manifest,
        idempotency_key="complete-current",
    )

    current = store.rebuild(
        current_snapshot,
        prior_candidate_manifest_sha256=prior.manifest_sha256,
        observation_through_session="2026-08-13",
    )

    assert current.observation_through_session == "2026-08-13"
    assert current.raw_batch_count == prior.raw_batch_count
    assert current.manifest_sha256 != prior.manifest_sha256
    assert store.validate(current.manifest_sha256) == current


def test_daily_rebuild_publishes_targeted_evidence_and_degraded_discovery_coverage(
    tmp_path: Path,
) -> None:
    store, prior, _repeated, snapshot = _materialized_candidate(tmp_path)
    accepted = tuple(
        replace(checkpoint, ordinal=ordinal)
        for ordinal, checkpoint in enumerate(
            checkpoint
            for checkpoint in snapshot.shards
            if checkpoint.instrument_id == "equity:000001.SZ"
        )
    )
    targeted = replace(
        snapshot,
        idempotency_key="daily-financial-20260813",
        target_count=len(accepted),
        shards=accepted,
    )

    current = store.rebuild_daily(
        targeted,
        prior_candidate_manifest_sha256=prior.manifest_sha256,
        discovery=FinancialDiscoveryPublication(
            baseline_session="2026-08-13",
            attempted_through_session="2026-08-13",
            complete_through_session="2026-08-13",
            source_lineage_sha256="f" * 64,
            readiness_status="ready_with_pending",
            pending_instrument_count=1,
            discovery_gap_count=0,
            earliest_unresolved_date="2026-08-13",
        ),
    )

    coverage = store.family_reference(current.manifest_sha256)["dataset_coverage"]
    assert coverage == {
        "kind": "financial-announcement-observation-range",
        "start": "2010-01-04",
        "discovery_baseline_session": "2026-08-13",
        "discovery_attempted_through_session": "2026-08-13",
        "discovery_complete_through_session": "2026-08-13",
        "historical_reconciliation_watermark": "2026-08-13",
        "revision_coverage": "cninfo-announcement-driven-tushare-observed",
        "seed_policy": "latest-pre-start-annual-flow-and-reported-stock-facts",
        "readiness_status": "ready_with_pending",
        "pending_instrument_count": 1,
        "discovery_gap_count": 0,
        "earliest_unresolved_date": "2026-08-13",
        "source_lineage_sha256": "f" * 64,
    }
    assert current.raw_batch_count == prior.raw_batch_count
    assert store.read_table(
        current.manifest_sha256, "income_statement_versions"
    ) == store.read_table(prior.manifest_sha256, "income_statement_versions")


def test_zero_trigger_daily_rebuild_reuses_validated_parent_without_historical_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, prior, _repeated, snapshot = _materialized_candidate(tmp_path)
    empty = replace(
        snapshot,
        idempotency_key="daily-financial-zero-trigger",
        target_count=0,
        shards=(),
    )
    prior_manifest = _read_manifest(tmp_path, prior.manifest_sha256)

    def reject_historical_read(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("zero-trigger daily refresh reopened historical evidence")

    monkeypatch.setattr(store, "_require_evidence_present", reject_historical_read)
    monkeypatch.setattr(store, "_canonical_versions", reject_historical_read)

    current = store.rebuild_daily(
        empty,
        prior_candidate_manifest_sha256=prior.manifest_sha256,
        discovery=FinancialDiscoveryPublication(
            baseline_session="2026-08-13",
            attempted_through_session="2026-08-13",
            complete_through_session="2026-08-13",
            source_lineage_sha256="e" * 64,
            readiness_status="ready",
            pending_instrument_count=0,
            discovery_gap_count=0,
            earliest_unresolved_date=None,
        ),
    )

    current_manifest = _read_manifest(tmp_path, current.manifest_sha256)
    assert current_manifest["tables"] == prior_manifest["tables"]
    assert current_manifest["raw_evidence"] == prior_manifest["raw_evidence"]
    assert current_manifest["quarantine"] == prior_manifest["quarantine"]
    assert current_manifest["source_collection"]["prior_candidate_manifest_sha256"] == (
        prior.manifest_sha256
    )
    assert store.validate(current.manifest_sha256) == current
    assert store.read_table(
        current.manifest_sha256, "income_statement_versions"
    ) == store.read_table(prior.manifest_sha256, "income_statement_versions")


def test_daily_composition_does_not_revalidate_the_published_parent_family(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market = _market_generation(tmp_path)
    store = FinancialCandidateStore(tmp_path)
    snapshot = _empty_complete_snapshot(
        tmp_path,
        market,
        idempotency_key="daily-composition-prior",
        fields=FULL_EXECUTABLE_FIELDS,
    )
    prior = store.materialize(snapshot, observation_through_session="2026-08-13")
    generations = MountedGenerationStore(tmp_path)
    source = generations.compose_financial_candidate(
        market,
        prior.manifest_sha256,
        prepared_at=datetime(2026, 8, 13, 9, tzinfo=UTC),
    )
    empty = replace(
        snapshot,
        idempotency_key="daily-financial-prevalidated-parent",
        generation_manifest_sha256=source.manifest_sha256,
        target_count=0,
        shards=(),
    )
    original_validate = FinancialCandidateStore.validate

    def bounded_validate(
        candidate_store: FinancialCandidateStore,
        manifest_sha256: str,
    ):
        if manifest_sha256 == prior.manifest_sha256:
            raise AssertionError("daily path revalidated the published parent Family")
        return original_validate(candidate_store, manifest_sha256)

    def reject_market_revalidation(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("daily path revalidated a published Market root")

    monkeypatch.setattr(FinancialCandidateStore, "validate", bounded_validate)
    monkeypatch.setattr(
        MountedGenerationStore,
        "validate_market_generation",
        reject_market_revalidation,
    )
    candidate = store.rebuild_daily(
        empty,
        prior_candidate_manifest_sha256=prior.manifest_sha256,
        discovery=FinancialDiscoveryPublication(
            baseline_session="2026-08-13",
            attempted_through_session="2026-08-13",
            complete_through_session="2026-08-13",
            source_lineage_sha256="a" * 64,
            readiness_status="ready",
            pending_instrument_count=0,
            discovery_gap_count=0,
            earliest_unresolved_date=None,
        ),
    )

    composed = generations.compose_financial_candidate(
        source.manifest_sha256,
        candidate.manifest_sha256,
        prepared_at=datetime(2026, 8, 13, 10, tzinfo=UTC),
    )

    assert composed.financial_candidate_manifest_sha256 == candidate.manifest_sha256


def test_targeted_daily_rebuild_reads_only_affected_instrument_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, prior, _repeated, snapshot = _materialized_candidate(tmp_path)
    accepted = tuple(
        replace(checkpoint, ordinal=ordinal)
        for ordinal, checkpoint in enumerate(
            checkpoint
            for checkpoint in snapshot.shards
            if checkpoint.instrument_id == "equity:000001.SZ"
        )
    )
    targeted = replace(
        snapshot,
        idempotency_key="daily-financial-targeted-read-bound",
        target_count=len(accepted),
        shards=accepted,
    )
    forbidden_hashes = {
        checkpoint.batch_sha256
        for checkpoint in snapshot.shards
        if checkpoint.instrument_id == "equity:000002.SZ"
    }
    original_read = store._read_raw_batch

    def bounded_read(batch_sha256: str) -> dict[str, object]:
        if batch_sha256 in forbidden_hashes:
            raise AssertionError("targeted refresh read an unaffected instrument raw batch")
        return original_read(batch_sha256)

    monkeypatch.setattr(store, "_read_raw_batch", bounded_read)

    current = store.rebuild_daily(
        targeted,
        prior_candidate_manifest_sha256=prior.manifest_sha256,
        discovery=FinancialDiscoveryPublication(
            baseline_session="2026-08-13",
            attempted_through_session="2026-08-13",
            complete_through_session="2026-08-13",
            source_lineage_sha256="d" * 64,
            readiness_status="ready",
            pending_instrument_count=0,
            discovery_gap_count=0,
            earliest_unresolved_date=None,
        ),
    )

    assert store.validate(current.manifest_sha256) == current
    current_manifest = _read_manifest(tmp_path, current.manifest_sha256)
    prior_manifest = _read_manifest(tmp_path, prior.manifest_sha256)
    assert current_manifest["tables"] == prior_manifest["tables"]


def test_daily_instrument_validation_reports_no_delta_for_identical_history(
    tmp_path: Path,
) -> None:
    store, prior, _repeated, snapshot = _materialized_candidate(tmp_path)
    targeted = _targeted_instrument_collection(
        snapshot,
        idempotency_key="daily-financial-identical-history",
    )

    changed = store.validate_daily_instrument(
        targeted,
        prior_candidate_manifest_sha256=prior.manifest_sha256,
        observation_through_session="2026-08-13",
    )

    assert changed is False


def test_daily_instrument_validation_ignores_raw_batch_only_change(
    tmp_path: Path,
) -> None:
    store, prior, _repeated, snapshot = _materialized_candidate(tmp_path)
    targeted = _append_targeted_source_row(
        tmp_path,
        _targeted_instrument_collection(
            snapshot,
            idempotency_key="daily-financial-raw-batch-only-change",
        ),
        endpoint="income",
        row=[
            "000001.SZ",
            "20090425",
            "",
            "20081231",
            "1",
            "1",
            "4",
            "81",
            "1",
        ],
    )

    changed = store.validate_daily_instrument(
        targeted,
        prior_candidate_manifest_sha256=prior.manifest_sha256,
        observation_through_session="2026-08-13",
    )

    assert changed is False


@pytest.mark.parametrize(
    "row",
    (
        ["000001.SZ", "20260813", "", "20260630", "1", "1", "2", "901", "0"],
        [
            "000001.SZ",
            "20090425",
            "20100422",
            "20081231",
            "1",
            "1",
            "4",
            "82",
            "1",
        ],
    ),
    ids=("new-report-period", "revised-value"),
)
def test_daily_instrument_validation_reports_canonical_row_delta(
    tmp_path: Path,
    row: list[object],
) -> None:
    store, prior, _repeated, snapshot = _materialized_candidate(tmp_path)
    targeted = _append_targeted_source_row(
        tmp_path,
        _targeted_instrument_collection(
            snapshot,
            idempotency_key="daily-financial-canonical-delta",
        ),
        endpoint="income",
        row=row,
    )

    changed = store.validate_daily_instrument(
        targeted,
        prior_candidate_manifest_sha256=prior.manifest_sha256,
        observation_through_session="2026-08-13",
    )

    assert changed is True


def test_daily_instrument_validation_reports_availability_session_delta(
    tmp_path: Path,
) -> None:
    store, prior, _repeated, snapshot = _materialized_candidate(tmp_path)
    next_market = _market_generation(
        tmp_path,
        sessions=(*SESSIONS, "2026-08-14"),
    )
    targeted = _targeted_instrument_collection(
        snapshot,
        idempotency_key="daily-financial-availability-delta",
        generation_manifest_sha256=next_market,
    )

    changed = store.validate_daily_instrument(
        targeted,
        prior_candidate_manifest_sha256=prior.manifest_sha256,
        observation_through_session="2026-08-14",
    )

    assert changed is True


def test_daily_instrument_validation_rejects_a_new_undated_source_row(
    tmp_path: Path,
) -> None:
    store, prior, _repeated, snapshot = _materialized_candidate(tmp_path)
    raw = RawFinancialBatchStore(tmp_path)
    targeted: list[FinancialShardCheckpoint] = []
    for checkpoint in snapshot.shards:
        if checkpoint.instrument_id != "equity:000001.SZ":
            continue
        assert checkpoint.batch_sha256 is not None
        payload = raw.read(checkpoint.batch_sha256)
        items = [*payload["items"]]
        if checkpoint.endpoint == "income":
            items.append(
                [
                    checkpoint.ts_code,
                    "",
                    "",
                    "20260630",
                    "1",
                    "1",
                    "2",
                    "999",
                    "0",
                ]
            )
        publications = [str(item[2] or item[1]) for item in items if item[2] or item[1]]
        payload["items"] = items
        payload["row_count"] = len(items)
        payload["source_date_extent"] = [min(publications), max(publications)]
        payload["payload_sha256"] = hashlib.sha256(
            canonical_json_bytes({"fields": list(FIELDS), "items": items})
        ).hexdigest()
        targeted.append(
            replace(
                checkpoint,
                ordinal=len(targeted),
                batch_sha256=raw.store(canonical_json_bytes(payload)),
                collected_at="2026-08-13T08:30:00+00:00",
                first_observed_at="2026-08-13T08:30:00+00:00",
            )
        )
    collection = replace(
        snapshot,
        idempotency_key="daily-financial-undated-row",
        target_count=len(targeted),
        shards=tuple(targeted),
    )

    with pytest.raises(
        FinancialCandidateError,
        match="FINANCIAL_DAILY_INSTRUMENT_INVALID",
    ):
        store.validate_daily_instrument(
            collection,
            prior_candidate_manifest_sha256=prior.manifest_sha256,
            observation_through_session="2026-08-13",
        )


def test_daily_instrument_validation_reads_the_parent_evidence_index_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, prior, _repeated, snapshot = _materialized_candidate(tmp_path)
    prior_manifest = _read_manifest(tmp_path, prior.manifest_sha256)
    evidence_index = _read_manifest(
        tmp_path,
        prior_manifest["raw_evidence"]["manifest_sha256"],
    )
    parent_chunk_hashes = {item["sha256"] for item in evidence_index["chunks"]}
    parent_chunk_reads = 0
    original_read_json = store._read_json

    def count_parent_chunk_reads(
        path: Path,
        sha256: str,
        byte_count: int | None = None,
    ) -> dict[str, object]:
        nonlocal parent_chunk_reads
        if sha256 in parent_chunk_hashes:
            parent_chunk_reads += 1
        return original_read_json(path, sha256, byte_count)

    monkeypatch.setattr(store, "_read_json", count_parent_chunk_reads)
    for instrument_id in ("equity:000001.SZ", "equity:000002.SZ"):
        checkpoints = tuple(
            replace(checkpoint, ordinal=ordinal)
            for ordinal, checkpoint in enumerate(
                item for item in snapshot.shards if item.instrument_id == instrument_id
            )
        )
        store.validate_daily_instrument(
            replace(
                snapshot,
                idempotency_key=f"daily-parent-index-{instrument_id}",
                target_count=len(checkpoints),
                shards=checkpoints,
            ),
            prior_candidate_manifest_sha256=prior.manifest_sha256,
            observation_through_session="2026-08-13",
        )

    assert parent_chunk_reads == len(parent_chunk_hashes)


def test_targeted_daily_rebuild_appends_only_changed_rows_to_immutable_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, prior, _repeated, snapshot = _materialized_candidate(tmp_path)
    raw = RawFinancialBatchStore(tmp_path)
    accepted: list[FinancialShardCheckpoint] = []
    for checkpoint in snapshot.shards:
        if checkpoint.instrument_id != "equity:000001.SZ":
            continue
        assert checkpoint.batch_sha256 is not None
        payload = raw.read(checkpoint.batch_sha256)
        items = [*payload["items"]]
        items.append(
            [
                checkpoint.ts_code,
                "20260813",
                "",
                "20260630",
                "1",
                "1",
                "2",
                f"{900 + len(accepted)}",
                "0",
            ]
        )
        publications = [str(item[2] or item[1]) for item in items if item[2] or item[1]]
        payload["items"] = items
        payload["row_count"] = len(items)
        payload["source_date_extent"] = [min(publications), max(publications)]
        payload["payload_sha256"] = hashlib.sha256(
            canonical_json_bytes({"fields": list(FIELDS), "items": items})
        ).hexdigest()
        accepted.append(
            replace(
                checkpoint,
                ordinal=len(accepted),
                batch_sha256=raw.store(canonical_json_bytes(payload)),
                collected_at="2026-08-13T08:30:00+00:00",
                first_observed_at="2026-08-13T08:30:00+00:00",
            )
        )
    targeted = replace(
        snapshot,
        idempotency_key="daily-financial-targeted-delta",
        target_count=len(accepted),
        shards=tuple(accepted),
    )
    forbidden_hashes = {
        checkpoint.batch_sha256
        for checkpoint in snapshot.shards
        if checkpoint.instrument_id == "equity:000002.SZ"
    }
    original_read = store._read_raw_batch

    def bounded_read(batch_sha256: str) -> dict[str, object]:
        if batch_sha256 in forbidden_hashes:
            raise AssertionError("targeted refresh read an unaffected instrument raw batch")
        return original_read(batch_sha256)

    monkeypatch.setattr(store, "_read_raw_batch", bounded_read)
    current = store.rebuild_daily(
        targeted,
        prior_candidate_manifest_sha256=prior.manifest_sha256,
        discovery=FinancialDiscoveryPublication(
            baseline_session="2026-08-13",
            attempted_through_session="2026-08-13",
            complete_through_session="2026-08-13",
            source_lineage_sha256="c" * 64,
            readiness_status="ready",
            pending_instrument_count=0,
            discovery_gap_count=0,
            earliest_unresolved_date=None,
        ),
    )

    assert store.validate(current.manifest_sha256) == current
    prior_manifest = _read_manifest(tmp_path, prior.manifest_sha256)
    current_manifest = _read_manifest(tmp_path, current.manifest_sha256)
    for prior_reference, current_reference in zip(
        prior_manifest["tables"], current_manifest["tables"], strict=True
    ):
        table = _read_manifest(tmp_path, current_reference["manifest_sha256"])
        prior_table = _read_manifest(tmp_path, prior_reference["manifest_sha256"])
        assert table["partitioning"]["kind"] == "immutable-base-with-delta-objects"
        assert table["partitioning"]["base_manifest_sha256"] == (
            prior_reference["manifest_sha256"]
        )
        assert table["objects"][: len(prior_table["objects"])] == prior_table["objects"]
        assert current_reference["object_count"] > prior_reference["object_count"]
    income = store.read_table(current.manifest_sha256, "income_statement_versions")
    assert sum(row["revenue"] == "900" for row in income) == 1
    retained = MountedGenerationStore(tmp_path).financial_candidate_referenced_files(
        current.manifest_sha256
    )
    assert GenerationFileRef("manifest", prior.manifest_sha256) in retained
    assert all(
        GenerationFileRef("manifest", reference["manifest_sha256"]) in retained
        for reference in prior_manifest["tables"]
    )

    second_checkpoints: list[FinancialShardCheckpoint] = []
    for checkpoint in accepted:
        assert checkpoint.batch_sha256 is not None
        payload = raw.read(checkpoint.batch_sha256)
        items = [*payload["items"]]
        items.append(
            [
                checkpoint.ts_code,
                "20260813",
                "",
                "20260630",
                "1",
                "1",
                "2",
                f"{950 + len(second_checkpoints)}",
                "0",
            ]
        )
        publications = [str(item[2] or item[1]) for item in items if item[2] or item[1]]
        payload["items"] = items
        payload["row_count"] = len(items)
        payload["source_date_extent"] = [min(publications), max(publications)]
        payload["payload_sha256"] = hashlib.sha256(
            canonical_json_bytes({"fields": list(FIELDS), "items": items})
        ).hexdigest()
        second_checkpoints.append(
            replace(
                checkpoint,
                ordinal=len(second_checkpoints),
                batch_sha256=raw.store(canonical_json_bytes(payload)),
                collected_at="2026-08-13T08:45:00+00:00",
                first_observed_at="2026-08-13T08:45:00+00:00",
            )
        )
    second = store.rebuild_daily(
        replace(
            targeted,
            idempotency_key="daily-financial-targeted-second-delta",
            shards=tuple(second_checkpoints),
        ),
        prior_candidate_manifest_sha256=current.manifest_sha256,
        discovery=FinancialDiscoveryPublication(
            baseline_session="2026-08-13",
            attempted_through_session="2026-08-13",
            complete_through_session="2026-08-13",
            source_lineage_sha256="b" * 64,
            readiness_status="ready",
            pending_instrument_count=0,
            discovery_gap_count=0,
            earliest_unresolved_date=None,
        ),
    )
    assert store.validate(second.manifest_sha256) == second
    second_income = store.read_table(second.manifest_sha256, "income_statement_versions")
    assert sum(row["revenue"] == "900" for row in second_income) == 1
    assert sum(row["revenue"] == "950" for row in second_income) == 1
    second_retained = MountedGenerationStore(tmp_path).financial_candidate_referenced_files(
        second.manifest_sha256
    )
    assert GenerationFileRef("manifest", current.manifest_sha256) in second_retained
    assert all(
        GenerationFileRef("manifest", reference["manifest_sha256"]) in second_retained
        for reference in current_manifest["tables"]
    )


def test_generation_admission_preserves_degraded_financial_readiness(
    tmp_path: Path,
) -> None:
    market = _market_generation(tmp_path)
    store = FinancialCandidateStore(tmp_path)
    prior = store.materialize(
        _empty_complete_snapshot(
            tmp_path,
            market,
            idempotency_key="readiness-prior",
            fields=FULL_EXECUTABLE_FIELDS,
        ),
        observation_through_session="2026-08-13",
    )
    generation_store = MountedGenerationStore(tmp_path)
    source = generation_store.compose_financial_candidate(
        market,
        prior.manifest_sha256,
        prepared_at=datetime(2026, 8, 13, 8, tzinfo=UTC),
    )
    empty = replace(
        _empty_complete_snapshot(
            tmp_path,
            source.manifest_sha256,
            idempotency_key="readiness-prior-daily",
            fields=FULL_EXECUTABLE_FIELDS,
        ),
        target_count=0,
        shards=(),
    )
    current = store.rebuild_daily(
        empty,
        prior_candidate_manifest_sha256=prior.manifest_sha256,
        discovery=FinancialDiscoveryPublication(
            baseline_session="2026-08-13",
            attempted_through_session="2026-08-13",
            complete_through_session="2026-08-13",
            source_lineage_sha256="f" * 64,
            readiness_status="ready_with_pending",
            pending_instrument_count=1,
            discovery_gap_count=0,
            earliest_unresolved_date="2026-08-13",
        ),
    )
    composite = generation_store.compose_financial_candidate(
        source.manifest_sha256,
        current.manifest_sha256,
        prepared_at=datetime(2026, 8, 13, 9, tzinfo=UTC),
        publication_coordinate="a" * 64,
    )
    assert composite.financial_research_readiness is not None
    assert composite.financial_research_readiness["status"] == "ready_with_pending"
    assert composite.financial_research_readiness[
        "attempted_through_session"
    ] == "2026-08-13"
    assert composite.financial_research_readiness[
        "complete_through_session"
    ] == "2026-08-13"
    admission = generation_store.open_admission(composite.manifest_sha256)
    assert admission.financial_research_readiness == "ready_with_pending"


def _empty_complete_snapshot(
    root: Path,
    market_manifest: str,
    *,
    idempotency_key: str,
    fields: tuple[str, ...] = FIELDS,
) -> CompletedFinancialCollection:
    raw = RawFinancialBatchStore(root)
    shards = (FinancialDateShard("complete-history"),)
    checkpoints: list[FinancialShardCheckpoint] = []
    payload_sha256 = hashlib.sha256(
        canonical_json_bytes({"fields": list(fields), "items": []})
    ).hexdigest()
    instruments = (
        ("equity:000001.SZ", "000001.SZ"),
        ("equity:000002.SZ", "000002.SZ"),
    )
    for endpoint in FINANCIAL_ENDPOINTS:
        for instrument_id, ts_code in instruments:
            for shard in shards:
                payload = {
                    "format": "thesistrace-raw-financial-batch",
                    "version": 1,
                    "source_contract_version": "tushare-financial-ordinary-v2",
                    "endpoint": endpoint,
                    "parameters": {"ts_code": ts_code, **shard.parameters()},
                    "returned_fields": list(fields),
                    "items": [],
                    "row_count": 0,
                    "source_date_extent": None,
                    "payload_sha256": payload_sha256,
                }
                checkpoints.append(
                    FinancialShardCheckpoint(
                        ordinal=len(checkpoints),
                        endpoint=endpoint,
                        instrument_id=instrument_id,
                        ts_code=ts_code,
                        shard=shard.name,
                        status="completed",
                        batch_sha256=raw.store(canonical_json_bytes(payload)),
                        collected_at="2026-08-13T08:00:00+00:00",
                        first_observed_at="2026-08-13T08:00:00+00:00",
                    )
                )
    contract = FinancialCollectionContract(
        capability_sha256=("c" if "prior" in idempotency_key else "d") * 64,
        endpoint_fields=tuple((endpoint, fields) for endpoint in FINANCIAL_ENDPOINTS),
        suspected_truncation_row_counts=tuple((endpoint, None) for endpoint in FINANCIAL_ENDPOINTS),
        shards=shards,
    )
    return CompletedFinancialCollection(
        idempotency_key=idempotency_key,
        generation_manifest_sha256=market_manifest,
        contract=contract,
        finished_at="2026-08-13T09:00:00+00:00",
        target_count=len(checkpoints),
        shards=tuple(checkpoints),
    )


def _market_generation(
    root: Path,
    *,
    include_second: bool = True,
    sessions: tuple[str, ...] = SESSIONS,
) -> str:
    canonical = build_minimal_canonical_fixture()
    template_price = dict(canonical["prices"][0])
    template_state = dict(canonical["trading_states"][0])
    template_limit = dict(canonical["price_limits"][0])
    template_pool = dict(canonical["base_pool"][0])
    template_universe = {
        name: dict(rows[0]) for name, rows in canonical["liquidity_universes"].items()
    }
    canonical["research_calendar"] = list(sessions)
    if include_second:
        canonical["instruments"] = [
            *canonical["instruments"],
            {
                "instrument_id": "equity:000002.SZ",
                "ts_code": "000002.SZ",
                "asset_type": "ordinary_a_share",
                "exchange": "SZSE",
                "board": "main",
                "listed_from": "2015-01-05",
                "listed_to": "2020-01-02",
            },
        ]
    canonical["prices"] = [dict(template_price, session=session) for session in sessions]
    canonical["trading_states"] = [
        dict(template_state, session=session) for session in sessions
    ]
    canonical["price_limits"] = [
        dict(template_limit, session=session) for session in sessions
    ]
    canonical["base_pool"] = [dict(template_pool, session=session) for session in sessions]
    canonical["liquidity_universes"] = {
        name: [dict(row, session=session) for session in sessions]
        for name, row in template_universe.items()
    }
    catalog = dict(canonical["field_catalog"][0])
    catalog["release_available_from"] = sessions[0]
    canonical["field_catalog"] = [catalog]
    return (
        MountedGenerationStore(root)
        .materialize(
            canonical,
            prepared_at=datetime(2026, 8, 13, tzinfo=UTC),
            source_name="financial-candidate-test",
            source_lineage={"fixture": "financial-candidate"},
        )
        .manifest_sha256
    )


def _read_manifest(root: Path, sha256: str) -> dict[str, object]:
    return json.loads(
        (
            root
            / "manifests"
            / "sha256"
            / sha256[:2]
            / f"{sha256}.json"
        ).read_bytes()
    )


def test_old_generation_keeps_its_field_subset_when_supported_catalog_grows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import thesistrace.data.fields as fields

    market = _market_generation(tmp_path)
    candidates = FinancialCandidateStore(tmp_path)
    candidate = candidates.materialize(
        _empty_complete_snapshot(
            tmp_path, market, idempotency_key="stable-field-subset",
            fields=FULL_EXECUTABLE_FIELDS,
        ),
        observation_through_session="2026-08-13",
    )
    store = MountedGenerationStore(tmp_path)
    generation = store.compose_financial_candidate(
        market, candidate.manifest_sha256,
        prepared_at=datetime(2026, 8, 13, 10, tzinfo=UTC),
    )
    extra = replace(
        fields.FINANCIAL_FIELDS[0],
        field_id="financial.income.test_amount.latest_fy",
        source_column="test_amount",
        alpha=fields.AlphaFieldCapability("test_amount"),
    )
    monkeypatch.setattr(fields, "FINANCIAL_FIELDS", (*fields.FINANCIAL_FIELDS, extra))
    monkeypatch.setattr(fields, "FIELD_DEFINITIONS", (*fields.FIELD_DEFINITIONS, extra))

    reopened = MountedGenerationStore(tmp_path).validate_generation(generation.manifest_sha256)
    assert reopened.field_availability == generation.field_availability
    assert extra.field_id not in reopened.field_availability
    refresh_base = store.open_refresh_base(generation.manifest_sha256)
    refreshed = store.materialize_refresh(
        predecessor_manifest_sha256=generation.manifest_sha256,
        replacement_canonical=refresh_base.canonical,
        replace_from_session=str(refresh_base.canonical["research_calendar"][-1]),
        prepared_at=datetime(2026, 8, 14, 10, tzinfo=UTC),
        source_name="market-refresh", source_lineage={"snapshot": "next-market"},
    )
    assert refreshed.field_availability == generation.field_availability
    assert refreshed.financial_research_readiness == generation.financial_research_readiness
    assert refreshed.families[-1] == generation.families[-1]
    assert store.open_admission(generation.manifest_sha256).financial_research_readiness == "ready"
    with pytest.raises(RuntimeError, match="unavailable in Generation"):
        store.read_composite_slice(
            generation.manifest_sha256,
            sessions=["2010-04-21"], universe_name="top300", neutralization="none",
            field_bindings={extra.field_id: "test_amount"},
        )


def test_industry_and_financial_publications_preserve_other_family_evidence(tmp_path: Path) -> None:
    market = _market_generation(tmp_path)
    store = MountedGenerationStore(tmp_path)
    candidate = FinancialCandidateStore(tmp_path).materialize(
        _empty_complete_snapshot(
            tmp_path, market, idempotency_key="family-preservation",
            fields=FULL_EXECUTABLE_FIELDS,
        ),
        observation_through_session="2026-08-13",
    )
    financial = store.compose_financial_candidate(
        market, candidate.manifest_sha256,
        prepared_at=datetime(2026, 8, 13, 10, tzinfo=UTC),
    )
    industry = store.materialize_industry_candidate(
        financial.manifest_sha256,
        [{
            "instrument_id": "equity:000001.SZ",
            "active_from": SESSIONS[0], "active_to": "",
            "sw2021_l1": "801780", "sw2021_l2": "801783", "sw2021_l3": "851911",
        }],
        observation_through_session=SESSIONS[-2],
    )
    combined = store.compose_industry_candidate(
        financial.manifest_sha256, industry.manifest_sha256,
        prepared_at=datetime(2026, 8, 13, 11, tzinfo=UTC),
        publication_coordinate="b" * 64,
    )
    assert {
        family.family_id: family for family in combined.families
        if family.family_id != "equity.industry_membership"
    } == {
        family.family_id: family for family in financial.families
        if family.family_id != "equity.industry_membership"
    }
    assert combined.field_availability == financial.field_availability
    assert combined.financial_research_readiness == financial.financial_research_readiness
    assert combined.financial_publication_coordinate == financial.financial_publication_coordinate
    assert store.validate_generation(combined.manifest_sha256) == combined
    from thesistrace.data.dependencies import generation_family_coverage

    coverage = generation_family_coverage(combined)
    assert coverage["equity.eod_price"].end.isoformat() == SESSIONS[-1]
    assert coverage["equity.financial_pit"].end.isoformat() == SESSIONS[-1]
    assert coverage["equity.industry_membership"].end.isoformat() == SESSIONS[-2]

    republished = store.compose_financial_candidate(
        combined.manifest_sha256, candidate.manifest_sha256,
        prepared_at=datetime(2026, 8, 13, 12, tzinfo=UTC),
    )
    assert republished.families == combined.families
    assert republished.field_availability == combined.field_availability
    assert republished.industry_publication_coordinate == combined.industry_publication_coordinate
    assert store.validate_generation(republished.manifest_sha256) == republished


def test_candidate_keeps_quarterly_cash_stock_and_annual_flow_start_seeds(tmp_path: Path) -> None:
    store, candidate, repeated, _ = _materialized_candidate(tmp_path, quarterly_cash_seed=True)
    assert candidate == repeated == store.reopen(candidate.manifest_sha256)
    rows = store.read_table(candidate.manifest_sha256, "cash_flow_statement_versions")
    seeds = [
        row for row in rows
        if row["instrument_id"] == "equity:000001.SZ"
        and row["coverage_role"] == "pre_start_seed"
    ]
    assert {row["source_report_period"] for row in seeds} == {"20081231", "20090331"}
    assert {row["revenue"] for row in seeds} == {"30", "45"}
    assert all(row["effective_available_session"] < candidate.coverage_start for row in seeds)
    assert candidate.coverage_start == "2010-01-04"
    assert store.validate(candidate.manifest_sha256) == candidate


def test_projector_quarantines_simultaneous_conflicts_without_choosing_payload_order() -> None:
    observations = tuple(
        FinancialSourceObservation(
            endpoint="balancesheet",
            instrument_id="equity:000001.SZ",
            ts_code="000001.SZ",
            source_fields=FIELDS,
            source_values=(
                "000001.SZ", "20100420", "", "20091231", "1", "1", "4", value, flag,
            ),
            first_observed_at="2026-04-24T08:00:00+00:00",
            raw_batch_sha256=digest * 64,
        )
        for value, flag, digest in (("100", "0", "a"), ("101", "1", "b"))
    )
    for ordered in (observations, tuple(reversed(observations))):
        versions = FinancialVersionProjector().project(ordered, SESSIONS)
        assert len(versions) == 2
        assert {version.availability_status for version in versions} == {"quarantined"}
        assert {version.coverage_role for version in versions} == {"quarantined"}
        assert {version.source()["revenue"] for version in versions} == {"100", "101"}
        assert all(not version.effective_available_session for version in versions)


def test_explicit_rebuild_reprojects_saved_receipts_without_new_source_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import thesistrace.data.financial_candidate as candidate_module

    with monkeypatch.context() as previous_catalog:
        previous_catalog.setattr(
            candidate_module, "FINANCIAL_FIELDS", candidate_module.FINANCIAL_FIELDS[:6],
        )
        store, prior, _, snapshot = _materialized_candidate(tmp_path, quarterly_cash_seed=True)
    rebuilt = store.rebuild(
        snapshot,
        prior_candidate_manifest_sha256=prior.manifest_sha256,
        observation_through_session=prior.observation_through_session,
    )
    assert rebuilt.manifest_sha256 != prior.manifest_sha256
    assert rebuilt.raw_batch_count == prior.raw_batch_count
    rows = store.read_table(rebuilt.manifest_sha256, "cash_flow_statement_versions")
    assert {
        row["source_report_period"] for row in rows
        if row["instrument_id"] == "equity:000001.SZ" and row["coverage_role"] == "pre_start_seed"
    } == {"20081231", "20090331"}
    old_rows = store.read_table(prior.manifest_sha256, "cash_flow_statement_versions")
    assert {
        row["source_report_period"] for row in old_rows
        if row["instrument_id"] == "equity:000001.SZ" and row["coverage_role"] == "pre_start_seed"
    } == {"20081231"}


def test_projector_preserves_equal_values_with_different_update_flags() -> None:
    observations = tuple(
        FinancialSourceObservation(
            endpoint="balancesheet",
            instrument_id="equity:000001.SZ",
            ts_code="000001.SZ",
            source_fields=FIELDS,
            source_values=(
                "000001.SZ", "20100420", "", "20091231", "1", "1", "4", "100", flag,
            ),
            first_observed_at="2026-04-24T08:00:00+00:00",
            raw_batch_sha256=digest * 64,
        )
        for flag, digest in (("0", "a"), ("1", "b"))
    )
    for ordered in (observations, tuple(reversed(observations))):
        versions = FinancialVersionProjector().project(ordered, SESSIONS)
        assert len(versions) == 2
        assert {version.availability_status for version in versions} == {"available"}
        assert {version.source()["revenue"] for version in versions} == {"100"}
        assert {version.source()["update_flag"] for version in versions} == {"0", "1"}
        assert {version.raw_batch_sha256 for version in versions} == {"a" * 64, "b" * 64}
        assert {version.effective_available_session for version in versions} == {"2010-04-21"}


@pytest.mark.parametrize("damage", [None, "raw", "object"])
def test_preserved_candidate_from_prior_code_retains_verified_bytes(
    tmp_path: Path, damage: str | None,
) -> None:
    import zipfile

    fixture = Path(__file__).parents[1] / "fixtures/financial-stored-facts/candidate-de55453.zip"
    with zipfile.ZipFile(fixture) as archive:
        archive.extractall(tmp_path)
    manifest = "afd76a941766d3471ec95a22383a9ce9ce4e10ec558a530b3e2e0c12eacf9917"
    store = FinancialCandidateStore(tmp_path)
    before = {
        str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    }
    if damage is not None:
        family_path = tmp_path / "manifests/sha256" / manifest[:2] / f"{manifest}.json"
        family = json.loads(family_path.read_text())
        if damage == "object":
            table_sha = family["tables"][0]["manifest_sha256"]
            table_path = tmp_path / "manifests/sha256" / table_sha[:2] / f"{table_sha}.json"
            table = json.loads(table_path.read_text())
            sha = table["objects"][0]["sha256"]
            path = tmp_path / "objects/sha256" / sha[:2] / f"{sha}.parquet"
        else:
            path = next((tmp_path / "financial/raw").rglob("*.json"))
        path.write_bytes(b"corrupt")
        with pytest.raises((FinancialCandidateError, RuntimeError)):
            MountedGenerationStore(tmp_path).financial_candidate_referenced_files(manifest)
        return
    assert store.validate_stored(manifest).manifest_sha256 == manifest
    assert MountedGenerationStore(tmp_path).financial_candidate_referenced_files(manifest)
    assert before == {
        str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize("columnar", [False, True])
def test_quarantined_stock_candidate_resolves_to_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, columnar: bool,
) -> None:
    monkeypatch.setitem(
        globals(), "FIELDS", tuple("money_cap" if name == "revenue" else name for name in FIELDS),
    )
    store, candidate, _, _ = _materialized_candidate(tmp_path)
    field = "financial.balance_sheet.monetary_funds.latest_reported"
    resolver = FinancialSeriesResolver(store)
    request = {
        "manifest_sha256": candidate.manifest_sha256,
        "field_ids": (field,),
        "sessions": ("2010-04-21",),
        "instrument_ids": ("equity:000001.SZ",),
    }
    if columnar:
        assert resolver.resolve_table(**request).to_pydict() == {
            "session": ["2010-04-21"],
            "instrument_id": ["equity:000001.SZ"],
            field: [None],
        }
    else:
        assert resolver.resolve(**request) == {field: {}}
