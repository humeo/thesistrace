from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from thesistrace.data.financial_candidate import (
    FinancialCandidateError,
    FinancialCandidateStore,
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
from thesistrace.data.generation_files import AddressedFileStore
from thesistrace.data.generation_store import MountedGenerationStore
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


def _materialized_candidate(tmp_path: Path):
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
            "source_contract_version": "tushare-financial-ordinary-v1",
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
        [["000001.SZ", "20090425", "", "20081231", "1", "1", "4", "30", "0"]],
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
    assert [row["revenue"] for row in income] == ["25", "81", "90", "101", None, "200"]
    assert [row["availability_status"] for row in income] == [
        "quarantined",
        "available",
        "available",
        "available",
        "available",
        "available",
    ]
    assert {row["revision_basis"] for row in income} == {"source_version"}
    assert [row["coverage_role"] for row in income] == [
        "quarantined",
        "pre_start_seed",
        "in_coverage",
        "in_coverage",
        "in_coverage",
        "in_coverage",
    ]
    assert income[0]["source_available_session"] == ""
    assert income[0]["effective_available_session"] == ""
    assert income[1]["source_available_session"] == "2009-04-27"
    assert income[1]["effective_available_session"] == "2009-04-27"
    assert income[2]["source_available_session"] == "2010-01-04"
    assert income[2]["coverage_role"] == "in_coverage"
    assert income[3]["source_available_session"] == "2010-04-21"
    assert income[3]["effective_available_session"] == "2010-04-21"
    assert income[4]["effective_available_session"] == "2010-04-21"
    assert income[5]["source_published_date"] == "20100421"
    assert income[5]["source_available_session"] == "2010-04-22"
    assert income[5]["source_report_type"] == "2"
    assert income[5]["source_company_type"] == "2"
    assert income[3]["source_row_sha256"] != income[4]["source_row_sha256"]
    assert income[3]["logical_revision_group_sha256"] == income[4]["logical_revision_group_sha256"]
    assert income[3]["source_batch_sha256"] == income[4]["source_batch_sha256"]
    assert store.quarantined_row_count(first.manifest_sha256) == 1
    assert {"70", "80"}.isdisjoint(row["revenue"] for row in income)
    balance = store.read_table(first.manifest_sha256, "balance_sheet_versions")
    pending_balance = [row for row in balance if row["availability_status"] == "pending_calendar"]
    assert {row["revenue"] for row in pending_balance} == {"999"}
    assert not (tmp_path / "HEAD.json").exists()


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


def test_materialization_rechecks_truncation_and_bounded_shard_cutoff(
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

    stale = replace(snapshot.contract, shards=_bounded_shards("20260812"))
    with pytest.raises(FinancialCandidateError, match="FINANCIAL_SHARD_CONTRACT_INCOMPLETE"):
        store.materialize(
            replace(snapshot, contract=stale),
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


def _bounded_shards(through: str) -> tuple[FinancialDateShard, ...]:
    start = date(1990, 1, 1)
    final = datetime.strptime(through, "%Y%m%d").date()
    shards: list[FinancialDateShard] = []
    while start <= final:
        end = min(start + timedelta(days=365), final)
        shards.append(
            FinancialDateShard(
                f"{start:%Y%m%d}-{end:%Y%m%d}",
                f"{start:%Y%m%d}",
                f"{end:%Y%m%d}",
            )
        )
        start = end + timedelta(days=1)
    return tuple(shards)


def _market_generation(root: Path) -> str:
    canonical = build_minimal_canonical_fixture()
    template_price = dict(canonical["prices"][0])
    template_state = dict(canonical["trading_states"][0])
    template_limit = dict(canonical["price_limits"][0])
    template_pool = dict(canonical["base_pool"][0])
    template_universe = {
        name: dict(rows[0]) for name, rows in canonical["liquidity_universes"].items()
    }
    canonical["research_calendar"] = list(SESSIONS)
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
    canonical["prices"] = [dict(template_price, session=session) for session in SESSIONS]
    canonical["trading_states"] = [dict(template_state, session=session) for session in SESSIONS]
    canonical["price_limits"] = [dict(template_limit, session=session) for session in SESSIONS]
    canonical["base_pool"] = [dict(template_pool, session=session) for session in SESSIONS]
    canonical["liquidity_universes"] = {
        name: [dict(row, session=session) for session in SESSIONS]
        for name, row in template_universe.items()
    }
    catalog = dict(canonical["field_catalog"][0])
    catalog["release_available_from"] = SESSIONS[0]
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
