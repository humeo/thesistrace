from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from thesistrace.data.generation_files import AddressedFileError, AddressedFileStore
from thesistrace.data.generation_schema import MARKET_CANDIDATE_TABLE_SPECS
from thesistrace.data.generation_store import (
    GENERATION_MANIFEST_MAX_BYTES,
    GENERATION_SESSION_PARTITION_COUNT,
    GenerationFileRef,
    GenerationStoreError,
    MountedFamilyGenerationDescriptor,
    MountedGenerationStore,
)
from thesistrace.data.source import (
    CanonicalBootstrapStream,
    CanonicalColumnarSessionPartition,
    CanonicalSessionPartition,
)
from thesistrace.publication.serialization import canonical_json_bytes


def test_streaming_bootstrap_materializes_the_same_generation(tmp_path: Path) -> None:
    canonical = _canonical()
    prepared_at = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    lineage = {"snapshot": "fixed"}
    in_memory = MountedGenerationStore(tmp_path / "in-memory").materialize(
        canonical,
        prepared_at=prepared_at,
        source_name="deterministic-test",
        source_lineage=lineage,
    )
    static = {
        key: canonical[key]
        for key in (
            "schema_version",
            "research_calendar",
            "instruments",
            "industry_membership",
            "field_catalog",
        )
    }
    calendar = [str(value) for value in canonical["research_calendar"]]

    def partitions() -> Iterator[CanonicalSessionPartition]:
        for start in range(0, len(calendar), GENERATION_SESSION_PARTITION_COUNT):
            sessions = tuple(calendar[start : start + GENERATION_SESSION_PARTITION_COUNT])
            selected = set(sessions)
            rows = {
                key: [row for row in canonical[key] if str(row["session"]) in selected]
                for key in ("prices", "trading_states", "price_limits", "base_pool")
            }
            rows["liquidity_universes"] = {
                name: [row for row in values if str(row["session"]) in selected]
                for name, values in canonical["liquidity_universes"].items()
            }
            yield CanonicalSessionPartition(sessions=sessions, canonical=rows)

    stream = CanonicalBootstrapStream(
        source_name="deterministic-test",
        source_lineage=lineage,
        static=static,
        covered_session_range=(
            str(canonical["research_calendar"][0]),
            str(canonical["research_calendar"][-1]),
        ),
        partitions=partitions,
    )

    streamed = MountedGenerationStore(tmp_path / "streamed").materialize_bootstrap_stream(
        stream,
        prepared_at=prepared_at,
    )

    assert streamed == in_memory


def test_columnar_streaming_bootstrap_materializes_the_same_generation(
    tmp_path: Path,
) -> None:
    canonical = _canonical()
    prepared_at = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    lineage = {"snapshot": "fixed"}
    static = {
        key: canonical[key]
        for key in (
            "schema_version",
            "research_calendar",
            "instruments",
            "industry_membership",
            "field_catalog",
        )
    }
    calendar = [str(value) for value in canonical["research_calendar"]]
    expected = MountedGenerationStore(tmp_path / "rows").materialize(
        canonical,
        prepared_at=prepared_at,
        source_name="deterministic-test",
        source_lineage=lineage,
    )

    def partitions() -> Iterator[CanonicalColumnarSessionPartition]:
        for start in range(0, len(calendar), GENERATION_SESSION_PARTITION_COUNT):
            sessions = tuple(calendar[start : start + GENERATION_SESSION_PARTITION_COUNT])
            selected = set(sessions)
            yield CanonicalColumnarSessionPartition(
                sessions=sessions,
                tables={
                    spec.name: pa.Table.from_pylist(
                        _columnar_candidate_rows(canonical, spec.name, selected),
                        schema=spec.contract.schema,
                    )
                    for spec in MARKET_CANDIDATE_TABLE_SPECS
                    if spec.session_field is not None and spec.name != "research_calendar"
                },
            )

    actual = MountedGenerationStore(tmp_path / "columnar").materialize_bootstrap_stream(
        CanonicalBootstrapStream(
            source_name="deterministic-test",
            source_lineage=lineage,
            static=static,
            covered_session_range=(calendar[0], calendar[-1]),
            partitions=partitions,
        ),
        prepared_at=prepared_at,
    )

    assert actual == expected


def _columnar_candidate_rows(
    canonical: dict[str, object],
    table: str,
    selected: set[str],
) -> list[dict[str, object]]:
    if table == "eod_prices":
        return [
            {
                "session_date": date.fromisoformat(str(row["session"])),
                "instrument_id": str(row["instrument_id"]),
                "open_raw": Decimal(str(row["open_raw"])),
                "high_raw": Decimal(str(row["high_raw"])),
                "low_raw": Decimal(str(row["low_raw"])),
                "close_raw": Decimal(str(row["close_raw"])),
                "pre_close_reference_raw": Decimal(str(row["pre_close_raw"])),
                "price_change_raw": Decimal(str(row["change_raw"])),
                "pct_change_ratio": Decimal(str(row["pct_change_raw"])) / Decimal(100),
                "volume_shares": int(str(row["volume_shares"])),
                "turnover_amount_cny": Decimal(str(row["turnover_cny"])),
                "adjustment_scale": Decimal(str(row["adjustment_factor"])),
                "open_adj": Decimal(str(row["open_adj"])),
                "high_adj": Decimal(str(row["high_adj"])),
                "low_adj": Decimal(str(row["low_adj"])),
                "close_adj": Decimal(str(row["close_adj"])),
            }
            for row in canonical["prices"]
            if str(row["session"]) in selected
        ]
    if table == "adjustment_factors":
        return [
            {
                "session_date": date.fromisoformat(str(row["session"])),
                "instrument_id": str(row["instrument_id"]),
                "source_adjustment_factor": Decimal(str(row["adjustment_factor"])),
            }
            for row in canonical["prices"]
            if str(row["session"]) in selected
        ]
    if table == "liquidity_universes":
        rows = [
            {"universe": name, **row}
            for name, values in canonical[table].items()
            for row in values
            if str(row["session"]) in selected
        ]
        return sorted(rows, key=lambda row: (str(row["session"]), str(row["universe"])))
    return [row for row in canonical[table] if str(row["session"]) in selected]


def test_generation_validation_does_not_accumulate_session_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MountedGenerationStore(tmp_path)
    generation = store.materialize(
        _canonical(),
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )
    original_open_table = store._open_table

    def reject_full_session_table(
        spec: object,
        reference: object,
        calendar: object,
    ) -> list[dict[str, object]]:
        if (
            getattr(spec, "session_field", None) is not None
            and getattr(spec, "name", None) != "research_calendar"
        ):
            raise AssertionError("validation accumulated a session table")
        return original_open_table(spec, reference, calendar)

    monkeypatch.setattr(store, "_open_table", reject_full_session_table)

    assert store.validate_generation(generation.manifest_sha256) == generation


def test_generation_preserves_data_unavailable_without_price_or_limit(
    tmp_path: Path,
) -> None:
    canonical = _canonical()
    missing_session = str(canonical["research_calendar"][0])
    missing_instrument = "equity:A.SH"
    missing_position = (missing_session, missing_instrument)
    for row in canonical["trading_states"]:
        if (str(row["session"]), str(row["instrument_id"])) == missing_position:
            row["state"] = "data_unavailable"
    for table in ("prices", "price_limits"):
        canonical[table] = [
            row
            for row in canonical[table]
            if (str(row["session"]), str(row["instrument_id"])) != missing_position
        ]
    for rows in canonical["liquidity_universes"].values():
        rows[0]["instrument_ids"] = [
            instrument_id
            for instrument_id in rows[0]["instrument_ids"]
            if instrument_id != missing_instrument
        ]

    store = MountedGenerationStore(tmp_path)
    generation = store.materialize(
        canonical,
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "data-unavailable"},
    )
    reopened = _open_all(store, generation.manifest_sha256)

    assert missing_position in {
        (row["session"], row["instrument_id"])
        for row in reopened["trading_states"]
        if row["state"] == "data_unavailable"
    }
    assert missing_position not in {
        (row["session"], row["instrument_id"]) for row in reopened["prices"]
    }
    assert missing_position not in {
        (row["session"], row["instrument_id"]) for row in reopened["price_limits"]
    }
    assert missing_instrument in reopened["base_pool"][0]["instrument_ids"]
    assert all(
        missing_instrument not in rows[0]["instrument_ids"]
        for rows in reopened["liquidity_universes"].values()
    )


def test_generation_preserves_price_with_unavailable_execution_state(
    tmp_path: Path,
) -> None:
    canonical = _canonical()
    session = str(canonical["research_calendar"][0])
    instrument_id = "equity:A.SH"
    for row in canonical["trading_states"]:
        if row["session"] == session and row["instrument_id"] == instrument_id:
            row["state"] = "data_unavailable"
    for row in canonical["prices"]:
        if row["session"] == session and row["instrument_id"] == instrument_id:
            row["trading_state"] = "data_unavailable"
    canonical["price_limits"] = [
        row
        for row in canonical["price_limits"]
        if row["session"] != session or row["instrument_id"] != instrument_id
    ]

    store = MountedGenerationStore(tmp_path)
    generation = store.materialize(
        canonical,
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "unavailable-execution-state"},
    )
    reopened = _open_all(store, generation.manifest_sha256)

    assert any(
        row["session"] == session
        and row["instrument_id"] == instrument_id
        and row["trading_state"] == "data_unavailable"
        for row in reopened["prices"]
    )
    assert not any(
        row["session"] == session and row["instrument_id"] == instrument_id
        for row in reopened["price_limits"]
    )


def test_family_generation_reopens_from_descriptors_without_publishing_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = _canonical()
    store = MountedGenerationStore(tmp_path)

    candidate = store.materialize(
        canonical,
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )

    def reject_parquet_read(*args: object, **kwargs: object) -> None:
        raise AssertionError("candidate descriptor inspection opened Parquet")

    reopened_store = MountedGenerationStore(tmp_path)
    with monkeypatch.context() as descriptor_only:
        descriptor_only.setattr(
            "thesistrace.data.generation_store.pq.read_table",
            reject_parquet_read,
        )
        reopened = reopened_store.inspect_root(candidate.manifest_sha256)
    validated = reopened_store.validate_generation(candidate.manifest_sha256)

    assert isinstance(reopened, MountedFamilyGenerationDescriptor)
    assert reopened == candidate
    assert validated == candidate
    assert reopened.schema_contract == "canonical-research"
    assert reopened.data_through_session == canonical["research_calendar"][-1]
    assert reopened.field_availability == (
        "market.turnover.cny",
        "price.close.adjusted",
    )
    assert [family.family_id for family in reopened.families] == [
        "market.research_calendar",
        "market.instrument_identity",
        "equity.eod_price",
        "equity.adjustment_factor",
        "equity.trading_state",
        "equity.price_limit",
        "equity.base_pool",
        "equity.liquidity_universe",
        "equity.industry_membership",
        "data.field_catalog",
    ]
    assert reopened.families[0].dataset_coverage == {
        "kind": "research-session-range",
        "start": canonical["research_calendar"][0],
        "end": canonical["research_calendar"][-1],
        "session_count": len(canonical["research_calendar"]),
    }
    assert reopened.families[1].dataset_coverage == {
        "kind": "instrument-set",
        "instrument_count": len(canonical["instruments"]),
    }
    assert reopened.families[-1].dataset_coverage == {
        "kind": "field-set",
        "field_count": len(canonical["field_catalog"]),
    }
    assert not (tmp_path / "HEAD.json").exists()

    root = _manifest(tmp_path, candidate.manifest_sha256)
    assert root["format"] == "thesistrace-family-generation"
    assert "dataset_coverage" not in root
    for family_reference in root["families"]:
        assert family_reference["dataset_coverage"]
        assert family_reference["validation_summary"]["status"] == "validated"
        family_manifest = _manifest(tmp_path, family_reference["manifest_sha256"])
        assert family_manifest["family_id"] == family_reference["family_id"]
        assert family_manifest["dataset_coverage"] == family_reference["dataset_coverage"]
        assert family_manifest["validation_summary"] == family_reference["validation_summary"]

    price_family = next(
        family for family in root["families"] if family["family_id"] == "equity.eod_price"
    )
    adjustment_family = next(
        family for family in root["families"] if family["family_id"] == "equity.adjustment_factor"
    )
    price_manifest = _manifest(tmp_path, price_family["manifest_sha256"])
    adjustment_manifest = _manifest(tmp_path, adjustment_family["manifest_sha256"])
    price_table = _manifest(
        tmp_path,
        price_manifest["tables"][0]["manifest_sha256"],
    )
    adjustment_table = _manifest(
        tmp_path,
        adjustment_manifest["tables"][0]["manifest_sha256"],
    )
    price_fields = {field["name"] for field in price_table["writer_contract"]["schema"]}
    adjustment_fields = {field["name"] for field in adjustment_table["writer_contract"]["schema"]}
    assert "adjustment_factor" not in price_fields
    assert "trading_state" not in price_fields
    assert {
        "session_date",
        "pre_close_reference_raw",
        "price_change_raw",
        "pct_change_ratio",
        "turnover_amount_cny",
        "adjustment_scale",
    } <= price_fields
    assert "source_adjustment_factor" in adjustment_fields
    assert (
        next(
            field
            for field in price_table["writer_contract"]["schema"]
            if field["name"] == "volume_shares"
        )["logical_type"]
        == "int64"
    )
    assert next(
        field for field in price_table["writer_contract"]["schema"] if field["name"] == "open_raw"
    )["logical_type"].startswith("decimal128")


def test_family_generation_reuses_manifests_and_objects_for_reordered_content(
    tmp_path: Path,
) -> None:
    canonical = _canonical()
    reordered = copy.deepcopy(canonical)
    for table in (
        "instruments",
        "prices",
        "trading_states",
        "price_limits",
        "base_pool",
        "industry_membership",
        "field_catalog",
    ):
        reordered[table] = list(reversed(reordered[table]))
    reordered["liquidity_universes"] = {
        name: list(reversed(rows))
        for name, rows in reversed(tuple(reordered["liquidity_universes"].items()))
    }
    store = MountedGenerationStore(tmp_path)
    preparation = {
        "prepared_at": datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        "source_name": "deterministic-test",
        "source_lineage": {"snapshot": "fixed"},
    }

    first = store.materialize(canonical, **preparation)
    first_inventory = store.inventory()
    second = store.materialize(reordered, **preparation)

    assert second == first
    assert store.inventory() == first_inventory


def test_market_slice_skips_unrequested_families_and_session_partitions(
    tmp_path: Path,
) -> None:
    canonical = _canonical(GENERATION_SESSION_PARTITION_COUNT * 3)
    for rows in canonical["liquidity_universes"].values():
        for row in rows:
            row["instrument_ids"] = ["equity:A.SH"]
    store = MountedGenerationStore(tmp_path)
    generation = store.materialize(
        canonical,
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )
    root = _manifest(tmp_path, generation.manifest_sha256)
    eod_family = next(
        family for family in root["families"] if family["family_id"] == "equity.eod_price"
    )
    eod_manifest = _manifest(tmp_path, eod_family["manifest_sha256"])
    eod_table = _manifest(tmp_path, eod_manifest["tables"][0]["manifest_sha256"])
    _object_path(tmp_path, eod_table["objects"][0]["sha256"]).write_bytes(b"unrequested")
    factor_family = next(
        family for family in root["families"] if family["family_id"] == "equity.adjustment_factor"
    )
    factor_manifest = _manifest(tmp_path, factor_family["manifest_sha256"])
    factor_table = _manifest(tmp_path, factor_manifest["tables"][0]["manifest_sha256"])
    for object_reference in factor_table["objects"]:
        _object_path(tmp_path, object_reference["sha256"]).write_bytes(b"unrequested")
    sessions = canonical["research_calendar"][-2:]
    market = store.read_market_slice(
        generation.manifest_sha256,
        sessions=sessions,
        universe_name="top300",
        neutralization="none",
        field_bindings={"price.close.adjusted": "close_adj"},
    )

    assert list(market.research_data.sessions) == sessions
    assert list(market.research_data.instruments) == ["equity:A.SH"]
    assert set(market.research_data.fields) == {"price.close.adjusted"}
    assert set(market.research_data.fields["price.close.adjusted"]) == {
        (session, "equity:A.SH") for session in sessions
    }


def test_market_slice_rejects_a_corrupt_selected_session_partition(
    tmp_path: Path,
) -> None:
    canonical = _canonical(GENERATION_SESSION_PARTITION_COUNT * 3)
    for rows in canonical["liquidity_universes"].values():
        for row in rows:
            row["instrument_ids"] = ["equity:A.SH"]
    store = MountedGenerationStore(tmp_path)
    generation = store.materialize(
        canonical,
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )
    root = _manifest(tmp_path, generation.manifest_sha256)
    eod_family = next(
        family for family in root["families"] if family["family_id"] == "equity.eod_price"
    )
    eod_manifest = _manifest(tmp_path, eod_family["manifest_sha256"])
    eod_table = _manifest(tmp_path, eod_manifest["tables"][0]["manifest_sha256"])
    selected_object = eod_table["objects"][-1]
    _object_path(tmp_path, selected_object["sha256"]).write_bytes(b"corrupt-selected")

    with pytest.raises(GenerationStoreError, match="byte count|checksum"):
        store.read_market_slice(
            generation.manifest_sha256,
            sessions=canonical["research_calendar"][-2:],
            universe_name="top300",
            neutralization="none",
            field_bindings={"price.close.adjusted": "close_adj"},
        )


def test_market_slice_projects_only_required_auxiliary_and_field_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MountedGenerationStore(tmp_path)
    generation = store.materialize(
        _canonical(),
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )
    projected_columns: list[tuple[str, ...] | None] = []
    original_iter_batches = pq.ParquetFile.iter_batches

    def recording_iter_batches(
        parquet: pq.ParquetFile,
        *args: object,
        **kwargs: object,
    ) -> Iterator[pa.RecordBatch]:
        columns = kwargs.get("columns")
        projected_columns.append(None if columns is None else tuple(columns))
        return original_iter_batches(parquet, *args, **kwargs)

    monkeypatch.setattr(pq.ParquetFile, "iter_batches", recording_iter_batches)

    store.read_market_slice(
        generation.manifest_sha256,
        sessions=_canonical()["research_calendar"][-2:],
        universe_name="top300",
        neutralization="industry",
        field_bindings={"price.close.adjusted": "close_adj"},
    )

    assert tuple(sorted(("instrument_id", "board", "listed_to"))) in projected_columns
    assert (
        tuple(sorted(("instrument_id", "active_from", "active_to", "sw2021_l1")))
        in projected_columns
    )
    assert (
        tuple(
            sorted(
                (
                    "session_date",
                    "instrument_id",
                    "open_raw",
                    "open_adj",
                    "turnover_amount_cny",
                    "close_adj",
                )
            )
        )
        in projected_columns
    )


def test_admission_reads_only_root_and_family_descriptors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation = MountedGenerationStore(tmp_path).materialize(
        _canonical(),
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
        source_name="test",
        source_lineage={"fixture": "admission"},
    )

    def reject_parquet(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("admission opened Parquet")

    monkeypatch.setattr("thesistrace.data.generation_store.pq.read_table", reject_parquet)

    admission = MountedGenerationStore(tmp_path).open_admission(generation.manifest_sha256)

    assert admission.research_calendar == tuple(_canonical()["research_calendar"])


@pytest.mark.parametrize(
    ("sessions", "universe", "neutralization", "field_bindings", "message"),
    [
        ([], "top300", "none", {"price.close.adjusted": "close_adj"}, "sessions"),
        (
            ["2026-08-05", "2026-08-04"],
            "top300",
            "none",
            {"price.close.adjusted": "close_adj"},
            "sessions",
        ),
        (
            ["2026-08-04"],
            "unknown",
            "none",
            {"price.close.adjusted": "close_adj"},
            "Universe",
        ),
        (
            ["2026-08-04"],
            "top300",
            "market",
            {"price.close.adjusted": "close_adj"},
            "Neutralization",
        ),
        (
            ["2026-08-04"],
            "top300",
            "none",
            {"price.close.adjusted": "unknown"},
            "binding",
        ),
    ],
)
def test_market_slice_rejects_invalid_explicit_selection(
    tmp_path: Path,
    sessions: list[str],
    universe: str,
    neutralization: str,
    field_bindings: dict[str, str],
    message: str,
) -> None:
    generation = MountedGenerationStore(tmp_path).materialize(
        _canonical(),
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
        source_name="test",
        source_lineage={"fixture": "selection"},
    )

    with pytest.raises(GenerationStoreError, match=message):
        MountedGenerationStore(tmp_path).read_market_slice(
            generation.manifest_sha256,
            sessions=sessions,
            universe_name=universe,
            neutralization=neutralization,
            field_bindings=field_bindings,
        )


@pytest.mark.parametrize("damage", ["missing", "corrupt", "mismatched"])
def test_family_generation_rejects_invalid_family_descriptors(
    tmp_path: Path,
    damage: str,
) -> None:
    store = MountedGenerationStore(tmp_path)
    candidate = store.materialize(
        _canonical(),
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )
    root = _manifest(tmp_path, candidate.manifest_sha256)
    family_reference = root["families"][0]
    family_path = _manifest_path(tmp_path, family_reference["manifest_sha256"])
    if damage == "missing":
        family_path.unlink()
    elif damage == "corrupt":
        family_path.write_bytes(b"corrupt")
    else:
        family_manifest = _manifest(tmp_path, family_reference["manifest_sha256"])
        family_manifest["family_id"] = "equity.wrong"
        mismatched_bytes = canonical_json_bytes(family_manifest)
        mismatched_sha256 = hashlib.sha256(mismatched_bytes).hexdigest()
        mismatched_path = _manifest_path(tmp_path, mismatched_sha256)
        mismatched_path.parent.mkdir(parents=True, exist_ok=True)
        mismatched_path.write_bytes(mismatched_bytes)
        root["families"][0]["manifest_sha256"] = mismatched_sha256
        root["families"][0]["manifest_byte_count"] = len(mismatched_bytes)
        identity = {
            "schema_contract": root["schema_contract"],
            "data_through_session": root["data_through_session"],
            "research_sessions": root["research_sessions"],
            "field_availability": root["field_availability"],
            "families": root["families"],
            "financial_research_readiness": root["financial_research_readiness"],
        }
        root["data_identity"] = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
        replacement_bytes = canonical_json_bytes(root)
        replacement_sha256 = hashlib.sha256(replacement_bytes).hexdigest()
        replacement_path = _manifest_path(tmp_path, replacement_sha256)
        replacement_path.parent.mkdir(parents=True, exist_ok=True)
        replacement_path.write_bytes(replacement_bytes)
        candidate = MountedFamilyGenerationDescriptor(
            manifest_sha256=replacement_sha256,
            data_identity=root["data_identity"],
            schema_contract=root["schema_contract"],
            data_through_session=root["data_through_session"],
            research_sessions=tuple(root["research_sessions"]),
            field_availability=tuple(root["field_availability"]),
            preparation=root["preparation"],
            families=candidate.families,
        )

    with pytest.raises(
        GenerationStoreError,
        match="missing|checksum|byte count|incompatible",
    ):
        store.validate_generation(candidate.manifest_sha256)


def test_family_generation_rejects_missing_physical_object(tmp_path: Path) -> None:
    store = MountedGenerationStore(tmp_path)
    candidate = store.materialize(
        _canonical(),
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )
    root = _manifest(tmp_path, candidate.manifest_sha256)
    family_reference = root["families"][0]
    family_manifest = _manifest(tmp_path, family_reference["manifest_sha256"])
    table_reference = family_manifest["tables"][0]
    table_manifest = _manifest(tmp_path, table_reference["manifest_sha256"])
    table_manifest["objects"][0]["sha256"] = "a" * 64
    table_sha256, table_bytes = _write_manifest(tmp_path, table_manifest)
    table_reference["manifest_sha256"] = table_sha256
    table_reference["manifest_byte_count"] = len(table_bytes)
    _replace_family_manifest(tmp_path, root, 0, family_manifest)
    replacement_sha256 = _write_candidate_root(tmp_path, root)

    with pytest.raises(GenerationStoreError, match="missing"):
        store.validate_generation(replacement_sha256)


def test_family_generation_rejects_wrong_physical_schema(tmp_path: Path) -> None:
    store = MountedGenerationStore(tmp_path)
    candidate = store.materialize(
        _canonical(),
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )
    root = _manifest(tmp_path, candidate.manifest_sha256)
    family_index = 0
    family_reference = root["families"][family_index]
    family_manifest = _manifest(tmp_path, family_reference["manifest_sha256"])
    table_reference = family_manifest["tables"][0]
    table_manifest = _manifest(tmp_path, table_reference["manifest_sha256"])
    output = pa.BufferOutputStream()
    pq.write_table(pa.table({"wrong": ["2024-01-02"]}), output)
    content = output.getvalue().to_pybytes()
    sha256 = hashlib.sha256(content).hexdigest()
    object_path = _object_path(tmp_path, sha256)
    object_path.parent.mkdir(parents=True, exist_ok=True)
    object_path.write_bytes(content)
    object_reference = table_manifest["objects"][0]
    object_reference["sha256"] = sha256
    object_reference["byte_count"] = len(content)
    table_sha256, table_bytes = _write_manifest(tmp_path, table_manifest)
    table_reference["manifest_sha256"] = table_sha256
    table_reference["manifest_byte_count"] = len(table_bytes)
    _replace_family_manifest(tmp_path, root, family_index, family_manifest)
    replacement_sha256 = _write_candidate_root(tmp_path, root)

    with pytest.raises(GenerationStoreError, match="schema is incompatible"):
        store.validate_generation(replacement_sha256)


def test_family_generation_rejects_self_consistent_shorter_family_coverage(
    tmp_path: Path,
) -> None:
    store = MountedGenerationStore(tmp_path)
    candidate = store.materialize(
        _canonical(),
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )
    root = _manifest(tmp_path, candidate.manifest_sha256)
    price_index = next(
        index
        for index, family in enumerate(root["families"])
        if family["family_id"] == "equity.eod_price"
    )
    price_reference = root["families"][price_index]
    price_manifest = _manifest(tmp_path, price_reference["manifest_sha256"])
    shorter = dict(price_reference["dataset_coverage"])
    shorter["start"] = shorter["end"]
    shorter["session_count"] = 1
    price_reference["dataset_coverage"] = shorter
    price_manifest["dataset_coverage"] = shorter
    _replace_family_manifest(tmp_path, root, price_index, price_manifest)
    replacement_sha256 = _write_candidate_root(tmp_path, root)

    with pytest.raises(GenerationStoreError, match="not synchronized"):
        store.validate_generation(replacement_sha256)


def test_family_generation_rejects_incomplete_preparation_metadata(
    tmp_path: Path,
) -> None:
    store = MountedGenerationStore(tmp_path)
    candidate = store.materialize(
        _canonical(),
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )
    root = _manifest(tmp_path, candidate.manifest_sha256)
    del root["preparation"]["source_name"]
    replacement_sha256 = _write_candidate_root(tmp_path, root)

    with pytest.raises(GenerationStoreError, match="preparation"):
        store.inspect_root(replacement_sha256)


def test_family_generation_rejects_coverage_not_backed_by_physical_data(
    tmp_path: Path,
) -> None:
    canonical = _canonical()
    canonical["field_catalog"] = canonical["field_catalog"][:1]
    store = MountedGenerationStore(tmp_path)
    candidate = store.materialize(
        canonical,
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )
    root = _manifest(tmp_path, candidate.manifest_sha256)
    catalog_index = next(
        index
        for index, family in enumerate(root["families"])
        if family["family_id"] == "data.field_catalog"
    )
    catalog_reference = root["families"][catalog_index]
    catalog_manifest = _manifest(tmp_path, catalog_reference["manifest_sha256"])
    false_coverage = {"kind": "field-set", "field_count": 2}
    catalog_reference["dataset_coverage"] = false_coverage
    catalog_manifest["dataset_coverage"] = false_coverage
    _replace_family_manifest(tmp_path, root, catalog_index, catalog_manifest)
    root["field_availability"] = [
        "market.turnover.cny",
        "price.close.adjusted",
    ]
    replacement_sha256 = _write_candidate_root(tmp_path, root)

    with pytest.raises(GenerationStoreError, match="root projection|Coverage projection"):
        store.validate_generation(replacement_sha256)


def test_materialized_generation_reopens_every_canonical_table_after_restart(
    tmp_path: Path,
) -> None:
    canonical = _canonical()
    store = MountedGenerationStore(tmp_path)

    materialized = store.materialize(
        canonical,
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )
    reopened = MountedGenerationStore(tmp_path).validate_generation(materialized.manifest_sha256)

    assert reopened.manifest_sha256 == materialized.manifest_sha256
    assert reopened.data_identity == materialized.data_identity
    assert reopened.families[0].dataset_coverage == {
        "kind": "research-session-range",
        "start": canonical["research_calendar"][0],
        "end": canonical["research_calendar"][-1],
        "session_count": len(canonical["research_calendar"]),
    }
    assert reopened.data_through_session == canonical["research_calendar"][-1]
    assert reopened.field_availability == (
        "market.turnover.cny",
        "price.close.adjusted",
    )
    assert reopened.preparation == {
        "prepared_at": "2026-08-09T00:00:00+00:00",
        "source_lineage_sha256": hashlib.sha256(
            canonical_json_bytes({"snapshot": "fixed"})
        ).hexdigest(),
        "source_name": "deterministic-test",
    }
    assert _open_all(MountedGenerationStore(tmp_path), materialized.manifest_sha256) == canonical

    root = _manifest(tmp_path, materialized.manifest_sha256)
    assert len(canonical_json_bytes(root)) <= GENERATION_MANIFEST_MAX_BYTES
    assert root["schema_contract"] == "canonical-research"
    assert "dataset_coverage" not in root
    assert "st_designations" not in {
        table_name for family in root["families"] for table_name in family["table_names"]
    }
    price_family = next(
        family for family in root["families"] if family["family_id"] == "equity.eod_price"
    )
    price_family_manifest = _manifest(tmp_path, price_family["manifest_sha256"])
    price_table = price_family_manifest["tables"][0]
    price_manifest = _manifest(tmp_path, price_table["manifest_sha256"])
    assert len(canonical_json_bytes(price_manifest)) <= GENERATION_MANIFEST_MAX_BYTES
    assert len(price_manifest["objects"]) == 2
    assert price_manifest["partitioning"] == {
        "kind": "research-session-block",
        "session_count": 64,
    }
    assert price_manifest["writer_contract"]["compression"]["codec"] == "zstd"


def test_reordered_source_rows_reuse_identical_physical_data_objects(tmp_path: Path) -> None:
    canonical = _canonical()
    reordered = copy.deepcopy(canonical)
    for table in (
        "instruments",
        "prices",
        "trading_states",
        "price_limits",
        "base_pool",
        "industry_membership",
        "field_catalog",
    ):
        reordered[table] = list(reversed(reordered[table]))
    reordered["liquidity_universes"] = {
        name: list(reversed(rows))
        for name, rows in reversed(tuple(reordered["liquidity_universes"].items()))
    }
    store = MountedGenerationStore(tmp_path)
    preparation = {
        "prepared_at": datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        "source_name": "deterministic-test",
        "source_lineage": {"snapshot": "fixed"},
    }

    first = store.materialize(canonical, **preparation)
    object_names = sorted(path.name for path in (tmp_path / "objects").rglob("*.parquet"))
    second = store.materialize(reordered, **preparation)

    assert second.data_identity == first.data_identity
    assert second.manifest_sha256 == first.manifest_sha256
    assert sorted(path.name for path in (tmp_path / "objects").rglob("*.parquet")) == object_names
    assert _open_all(MountedGenerationStore(tmp_path), second.manifest_sha256) == canonical


@pytest.mark.parametrize("session_count", (22, 4_000))
def test_refresh_window_and_rewritten_partition_count_do_not_grow_with_history(
    tmp_path: Path,
    session_count: int,
) -> None:
    canonical = _canonical(session_count)
    store = MountedGenerationStore(tmp_path)
    current = store.materialize(
        canonical,
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "current"},
    )

    refresh_base = store.open_refresh_base(current.manifest_sha256)
    replacement = copy.deepcopy(refresh_base.canonical)
    prices = replacement["prices"]
    assert isinstance(prices, list)
    prices[-1]["turnover_cny"] = "999999.00"
    replace_from_session = str(replacement["research_calendar"][-20])
    candidate = store.materialize_refresh(
        predecessor_manifest_sha256=current.manifest_sha256,
        replacement_canonical=replacement,
        replace_from_session=replace_from_session,
        prepared_at=datetime(2026, 8, 10, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "refresh"},
    )

    assert len(refresh_base.canonical["research_calendar"]) <= 39
    current_root = _manifest(tmp_path, current.manifest_sha256)
    candidate_root = _manifest(tmp_path, candidate.manifest_sha256)
    current_prices = _family_table_object_sha256s(
        tmp_path, current_root, "equity.eod_price", "eod_prices"
    )
    candidate_prices = _family_table_object_sha256s(
        tmp_path, candidate_root, "equity.eod_price", "eod_prices"
    )
    assert len(set(candidate_prices) - set(current_prices)) == 1
    assert candidate_prices[:-1] == current_prices[:-1]

    reopened = _open_all(store, candidate.manifest_sha256)
    expected = copy.deepcopy(canonical)
    expected["prices"][-1]["turnover_cny"] = "999999.00"
    assert reopened == expected


def test_refresh_does_not_open_immutable_partitions_before_its_window(
    tmp_path: Path,
) -> None:
    canonical = _canonical(GENERATION_SESSION_PARTITION_COUNT * 3)
    store = MountedGenerationStore(tmp_path)
    current = store.materialize(
        canonical,
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "current"},
    )
    current_root = _manifest(tmp_path, current.manifest_sha256)
    first_price_object = _family_table_object_sha256s(
        tmp_path,
        current_root,
        "equity.eod_price",
        "eod_prices",
    )[0]
    immutable_path = _object_path(tmp_path, first_price_object)
    immutable_bytes = immutable_path.read_bytes()
    immutable_path.write_bytes(b"outside-refresh-window")

    refresh_base = store.open_refresh_base(current.manifest_sha256)
    replacement = copy.deepcopy(refresh_base.canonical)
    replacement["prices"][-1]["turnover_cny"] = "999999.00"
    replace_from_session = str(replacement["research_calendar"][-20])
    candidate = store.materialize_refresh(
        predecessor_manifest_sha256=current.manifest_sha256,
        replacement_canonical=replacement,
        replace_from_session=replace_from_session,
        prepared_at=datetime(2026, 8, 10, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "refresh"},
    )

    immutable_path.write_bytes(immutable_bytes)
    assert store.validate_generation(candidate.manifest_sha256) == candidate


def test_reference_inventory_does_not_reopen_parquet_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MountedGenerationStore(tmp_path)
    generation = store.materialize(
        _canonical(22),
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "current"},
    )

    def reject_parquet_open(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("reference inventory must not open Parquet")

    monkeypatch.setattr(store, "_open_partition", reject_parquet_open)

    references = store.referenced_files(generation.manifest_sha256)

    assert GenerationFileRef("manifest", generation.manifest_sha256) in references


def test_admission_projection_opens_only_research_calendar(
    tmp_path: Path,
) -> None:
    canonical = _canonical()
    store = MountedGenerationStore(tmp_path)
    generation = store.materialize(
        canonical,
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )
    root = _manifest(tmp_path, generation.manifest_sha256)
    price_family = next(
        reference for reference in root["families"] if reference["family_id"] == "equity.eod_price"
    )
    price_family_manifest = _manifest(tmp_path, price_family["manifest_sha256"])
    price_manifest = _manifest(tmp_path, price_family_manifest["tables"][0]["manifest_sha256"])
    _object_path(tmp_path, price_manifest["objects"][0]["sha256"]).unlink()

    admission = MountedGenerationStore(tmp_path).open_admission(generation.manifest_sha256)

    assert admission.generation.manifest_sha256 == generation.manifest_sha256
    assert admission.generation.families[0].dataset_coverage == {
        "kind": "research-session-range",
        "start": canonical["research_calendar"][0],
        "end": canonical["research_calendar"][-1],
        "session_count": len(canonical["research_calendar"]),
    }
    assert admission.generation.field_availability == (
        "market.turnover.cny",
        "price.close.adjusted",
    )
    assert admission.research_calendar == tuple(canonical["research_calendar"])
    assert store.maximum_universe_cardinality(
        generation.manifest_sha256,
        universe="top3000",
        start_session=str(canonical["research_calendar"][0]),
        end_session=str(canonical["research_calendar"][-1]),
    ) == max(
        len({str(instrument_id) for instrument_id in row["instrument_ids"]})
        for row in canonical["liquidity_universes"]["top3000"]
    )
    with pytest.raises(GenerationStoreError, match="missing"):
        MountedGenerationStore(tmp_path).validate_generation(generation.manifest_sha256)


def test_universe_count_uses_manifest_statistics_without_parquet_scans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = _canonical(session_count=GENERATION_SESSION_PARTITION_COUNT * 2 + 1)
    store = MountedGenerationStore(tmp_path)
    generation = store.materialize(
        canonical,
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )
    opened: list[int] = []
    original = store._open_partition_projection

    def record_partition(spec, object_ref, ordinal, *, columns, instrument_ids):
        if spec.name == "liquidity_universes":
            opened.append(ordinal)
        return original(
            spec,
            object_ref,
            ordinal,
            columns=columns,
            instrument_ids=instrument_ids,
        )

    monkeypatch.setattr(store, "_open_partition_projection", record_partition)
    final_session = str(canonical["research_calendar"][-1])

    assert (
        store.maximum_universe_cardinality(
            generation.manifest_sha256,
            universe="top3000",
            start_session=final_session,
            end_session=final_session,
        )
        == 2
    )
    assert opened == []


def test_maximum_universe_cardinality_does_not_count_membership_churn(
    tmp_path: Path,
) -> None:
    canonical = _canonical(session_count=4)
    for rows in canonical["liquidity_universes"].values():
        for ordinal, row in enumerate(rows):
            row["instrument_ids"] = ["equity:A.SH" if ordinal % 2 == 0 else "equity:B.SZ"]
    store = MountedGenerationStore(tmp_path)
    generation = store.materialize(
        canonical,
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "membership-churn"},
    )

    assert (
        store.maximum_universe_cardinality(
            generation.manifest_sha256,
            universe="top3000",
            start_session=str(canonical["research_calendar"][0]),
            end_session=str(canonical["research_calendar"][-1]),
        )
        == 1
    )


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_missing_or_corrupt_object_is_never_reopened_as_a_generation(
    tmp_path: Path,
    damage: str,
) -> None:
    store = MountedGenerationStore(tmp_path)
    generation = store.materialize(
        _canonical(),
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )
    root = _manifest(tmp_path, generation.manifest_sha256)
    family = _manifest(tmp_path, root["families"][0]["manifest_sha256"])
    table = _manifest(tmp_path, family["tables"][0]["manifest_sha256"])
    object_sha256 = table["objects"][0]["sha256"]
    object_path = _object_path(tmp_path, object_sha256)
    if damage == "missing":
        object_path.unlink()
    else:
        object_path.write_bytes(b"corrupt")

    with pytest.raises(GenerationStoreError, match="missing|checksum|byte count"):
        MountedGenerationStore(tmp_path).validate_generation(generation.manifest_sha256)

    if damage == "corrupt":
        with pytest.raises(GenerationStoreError, match="immutable"):
            store.materialize(
                _canonical(),
                prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
                source_name="deterministic-test",
                source_lineage={"snapshot": "fixed"},
            )


def test_partial_or_incompatible_manifest_is_rejected(tmp_path: Path) -> None:
    store = MountedGenerationStore(tmp_path)
    generation = store.materialize(
        _canonical(),
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )
    _manifest_path(tmp_path, generation.manifest_sha256).write_bytes(b'{"format":')
    with pytest.raises(GenerationStoreError, match="checksum"):
        store.validate_generation(generation.manifest_sha256)

    incompatible = canonical_json_bytes(
        {"format": "thesistrace-canonical-generation", "version": 2}
    )
    incompatible_sha256 = hashlib.sha256(incompatible).hexdigest()
    incompatible_path = _manifest_path(tmp_path, incompatible_sha256)
    incompatible_path.parent.mkdir(parents=True, exist_ok=True)
    incompatible_path.write_bytes(incompatible)
    with pytest.raises(GenerationStoreError, match="incompatible"):
        store.validate_generation(incompatible_sha256)


def test_inconsistent_adjusted_price_derivation_is_rejected(tmp_path: Path) -> None:
    canonical = _canonical()
    canonical["prices"][0]["close_adj"] = "999.00000000"

    with pytest.raises(GenerationStoreError, match="derivation"):
        MountedGenerationStore(tmp_path).materialize(
            canonical,
            prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
            source_name="deterministic-test",
            source_lineage={"snapshot": "fixed"},
        )


def test_base_pool_cannot_include_an_instrument_after_terminal_delisting(
    tmp_path: Path,
) -> None:
    canonical = _canonical()
    canonical["instruments"][0]["listed_to"] = canonical["research_calendar"][1]

    with pytest.raises(GenerationStoreError, match="Base Pool membership is invalid"):
        MountedGenerationStore(tmp_path).materialize(
            canonical,
            prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
            source_name="deterministic-test",
            source_lineage={"snapshot": "fixed"},
        )


def test_oversized_or_symlinked_addressed_files_are_rejected_before_parsing(
    tmp_path: Path,
) -> None:
    oversized_sha256 = "0" * 64
    oversized = _manifest_path(tmp_path, oversized_sha256)
    oversized.parent.mkdir(parents=True)
    with oversized.open("wb") as stream:
        stream.truncate(GENERATION_MANIFEST_MAX_BYTES + 1)
    with pytest.raises(GenerationStoreError, match="byte bound"):
        MountedGenerationStore(tmp_path).validate_generation(oversized_sha256)

    store = MountedGenerationStore(tmp_path)
    generation = store.materialize(
        _canonical(),
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )
    root = _manifest(tmp_path, generation.manifest_sha256)
    family = _manifest(tmp_path, root["families"][0]["manifest_sha256"])
    table = _manifest(tmp_path, family["tables"][0]["manifest_sha256"])
    object_path = _object_path(tmp_path, table["objects"][0]["sha256"])
    external = tmp_path / "external.parquet"
    external.write_bytes(object_path.read_bytes())
    object_path.unlink()
    object_path.symlink_to(external)
    with pytest.raises(GenerationStoreError, match="unsafe"):
        store.validate_generation(generation.manifest_sha256)


def test_parent_directory_symlink_cannot_escape_the_mount(tmp_path: Path) -> None:
    external = tmp_path.parent / f"{tmp_path.name}-external"
    external.mkdir()
    (tmp_path / "objects").symlink_to(external, target_is_directory=True)

    with pytest.raises(GenerationStoreError, match="unsafe"):
        MountedGenerationStore(tmp_path).materialize(
            _canonical(),
            prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
            source_name="deterministic-test",
            source_lineage={"snapshot": "fixed"},
        )

    assert not tuple(external.iterdir())


def test_fifo_object_is_rejected_without_blocking(tmp_path: Path) -> None:
    store = MountedGenerationStore(tmp_path)
    generation = store.materialize(
        _canonical(),
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )
    root = _manifest(tmp_path, generation.manifest_sha256)
    family = _manifest(tmp_path, root["families"][0]["manifest_sha256"])
    table = _manifest(tmp_path, family["tables"][0]["manifest_sha256"])
    object_path = _object_path(tmp_path, table["objects"][0]["sha256"])
    object_path.unlink()
    os.mkfifo(object_path)

    with pytest.raises(GenerationStoreError, match="regular file"):
        store.validate_generation(generation.manifest_sha256)


def test_concurrent_materializers_publish_one_identical_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barrier = threading.Barrier(8)
    lock = threading.Lock()
    competing_threads: set[int] = set()
    real_link = os.link

    def racing_link(*args: object, **kwargs: object) -> None:
        identity = threading.get_ident()
        with lock:
            first_install = identity not in competing_threads
            competing_threads.add(identity)
        if first_install:
            barrier.wait(timeout=10)
        real_link(*args, **kwargs)

    monkeypatch.setattr(os, "link", racing_link)

    def materialize() -> tuple[str, str]:
        generation = MountedGenerationStore(tmp_path).materialize(
            _canonical(),
            prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
            source_name="deterministic-test",
            source_lineage={"snapshot": "fixed"},
        )
        return generation.manifest_sha256, generation.data_identity

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = tuple(executor.map(lambda _: materialize(), range(16)))

    assert len(set(outcomes)) == 1
    assert len(competing_threads) == 8
    manifest_sha256, _ = outcomes[0]
    assert _open_all(MountedGenerationStore(tmp_path), manifest_sha256) == _canonical()


def test_directory_sync_failure_never_exposes_a_complete_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from thesistrace.data import generation_files

    linked = False
    real_link = os.link
    real_sync = generation_files._fsync_directory

    def tracked_link(*args: object, **kwargs: object) -> None:
        nonlocal linked
        real_link(*args, **kwargs)
        linked = True

    def failing_sync(descriptor: int) -> None:
        if linked:
            raise OSError("injected directory fsync failure")
        real_sync(descriptor)

    monkeypatch.setattr(os, "link", tracked_link)
    monkeypatch.setattr(generation_files, "_fsync_directory", failing_sync)
    with pytest.raises(GenerationStoreError, match="filesystem write failed"):
        MountedGenerationStore(tmp_path).materialize(
            _canonical(),
            prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
            source_name="deterministic-test",
            source_lineage={"snapshot": "fixed"},
        )

    assert not tuple((tmp_path / "manifests").rglob("*.json"))


def test_link_failure_is_wrapped_and_never_exposes_a_complete_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_link(*args: object, **kwargs: object) -> None:
        raise OSError("injected link failure")

    monkeypatch.setattr(os, "link", failing_link)
    with pytest.raises(GenerationStoreError, match="filesystem write failed"):
        MountedGenerationStore(tmp_path).materialize(
            _canonical(),
            prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
            source_name="deterministic-test",
            source_lineage={"snapshot": "fixed"},
        )

    assert not tuple((tmp_path / "manifests").rglob("*.json"))


def test_link_race_loser_syncs_the_winner_directory_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from thesistrace.data import generation_files

    content = b"identical addressed content"
    sha256 = hashlib.sha256(content).hexdigest()
    target = tmp_path / "objects" / "sha256" / sha256[:2] / f"{sha256}.bin"
    barrier = threading.Barrier(2)
    winner_ready = threading.Event()
    winner_id: int | None = None
    winner_failed = False
    real_link = os.link
    real_sync = generation_files._fsync_directory

    def racing_link(*args: object, **kwargs: object) -> None:
        nonlocal winner_id
        barrier.wait(timeout=10)
        try:
            real_link(*args, **kwargs)
        except FileExistsError:
            assert winner_ready.wait(timeout=10)
            raise
        winner_id = threading.get_ident()
        winner_ready.set()

    def winner_sync_fails_once(descriptor: int) -> None:
        nonlocal winner_failed
        if threading.get_ident() == winner_id and not winner_failed:
            winner_failed = True
            raise OSError("injected winner directory fsync failure")
        real_sync(descriptor)

    monkeypatch.setattr(os, "link", racing_link)
    monkeypatch.setattr(generation_files, "_fsync_directory", winner_sync_fails_once)

    def attempt() -> str:
        try:
            AddressedFileStore(tmp_path).store(target, sha256, content)
        except AddressedFileError:
            return "failed"
        return "succeeded"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _: attempt(), range(2)))

    assert sorted(outcomes) == ["failed", "succeeded"]
    assert winner_failed
    assert (
        AddressedFileStore(tmp_path).read(
            target,
            sha256,
            expected_byte_count=len(content),
            max_byte_count=len(content),
        )
        == content
    )


def test_addressed_file_deletion_is_idempotent_and_cannot_follow_a_symlink(
    tmp_path: Path,
) -> None:
    content = b"retired immutable object"
    sha256 = hashlib.sha256(content).hexdigest()
    target = tmp_path / "objects" / "sha256" / sha256[:2] / f"{sha256}.parquet"
    files = AddressedFileStore(tmp_path)
    files.store(target, sha256, content)

    assert files.delete(target) is True
    assert files.delete(target) is False

    external = tmp_path.parent / f"{tmp_path.name}-external"
    external.write_bytes(b"must remain")
    target.symlink_to(external)
    with pytest.raises(AddressedFileError, match="unsafe"):
        files.delete(target)
    assert external.read_bytes() == b"must remain"


def _open_all(store: MountedGenerationStore, manifest_sha256: str) -> dict[str, object]:
    return store.open_refresh_base(
        manifest_sha256,
        overlap_session_count=100_000,
        universe_lookback_session_count=99_999,
    ).canonical


def _canonical(
    session_count: int = GENERATION_SESSION_PARTITION_COUNT + 1,
) -> dict[str, object]:
    sessions = _research_sessions(session_count)
    instruments = (
        {
            "instrument_id": "equity:A.SH",
            "ts_code": "A.SH",
            "asset_type": "ordinary_a_share",
            "exchange": "SSE",
            "board": "main",
            "listed_from": sessions[0],
            "listed_to": "",
        },
        {
            "instrument_id": "equity:B.SZ",
            "ts_code": "B.SZ",
            "asset_type": "ordinary_a_share",
            "exchange": "SZSE",
            "board": "main",
            "listed_from": sessions[0],
            "listed_to": "",
        },
    )
    prices: list[dict[str, str]] = []
    states: list[dict[str, str]] = []
    limits: list[dict[str, str]] = []
    base_pool: list[dict[str, object]] = []
    universes = {name: [] for name in ("top300", "top1000", "top2000", "top3000")}
    for ordinal, session in enumerate(sessions):
        members = ["equity:A.SH", "equity:B.SZ"]
        ranked_members = ["equity:B.SZ", "equity:A.SH"]
        base_pool.append({"session": session, "instrument_ids": members})
        for universe_rows in universes.values():
            universe_rows.append(
                {
                    "session": session,
                    "instrument_ids": ranked_members,
                    "status": "available",
                }
            )
        for instrument_index, instrument_id in enumerate(members):
            raw = 10 + ordinal + instrument_index
            states.append({"session": session, "instrument_id": instrument_id, "state": "normal"})
            prices.append(
                {
                    "session": session,
                    "instrument_id": instrument_id,
                    "open_raw": f"{raw}.0000",
                    "high_raw": f"{raw + 1}.0000",
                    "low_raw": f"{raw - 1}.0000",
                    "close_raw": f"{raw}.5000",
                    "pre_close_raw": f"{raw}.0000",
                    "change_raw": "0.5000",
                    "pct_change_raw": "5.000000",
                    "volume_shares": "10000",
                    "turnover_cny": f"{raw * 10000}.00",
                    "adjustment_factor": "1.000000",
                    "open_adj": f"{raw}.00000000",
                    "high_adj": f"{raw + 1}.00000000",
                    "low_adj": f"{raw - 1}.00000000",
                    "close_adj": f"{raw}.50000000",
                    "trading_state": "normal",
                }
            )
            limits.append(
                {
                    "session": session,
                    "instrument_id": instrument_id,
                    "upper": f"{raw + 1}.0000",
                    "lower": f"{raw - 1}.0000",
                }
            )
    return {
        "schema_version": "canonical-eod",
        "research_calendar": sessions,
        "instruments": list(instruments),
        "prices": prices,
        "trading_states": states,
        "price_limits": limits,
        "base_pool": base_pool,
        "liquidity_universes": universes,
        "industry_membership": [
            {
                "instrument_id": instrument["instrument_id"],
                "active_from": sessions[0],
                "active_to": "",
                "sw2021_l1": "L1",
                "sw2021_l2": "L2",
                "sw2021_l3": "L3",
            }
            for instrument in instruments
        ],
        "field_catalog": [
            {
                "name": "turnover_amount_cny",
                "field_id": "market.turnover.cny",
                "definition": "turnover amount",
                "unit": "CNY",
                "time_semantics": "post-close",
                "alpha_authorable": True,
                "release_available_from": sessions[-1],
                "coverage": "canonical EOD price rows",
            },
            {
                "name": "close_adj",
                "field_id": "price.close.adjusted",
                "definition": "adjusted close",
                "unit": "CNY/share",
                "time_semantics": "post-close",
                "alpha_authorable": True,
                "release_available_from": sessions[-1],
                "coverage": "canonical EOD price rows",
            },
        ],
    }


def _research_sessions(count: int) -> list[str]:
    current = date(2024, 1, 2)
    sessions: list[str] = []
    while len(sessions) < count:
        if current.weekday() < 5:
            sessions.append(current.isoformat())
        current += timedelta(days=1)
    return sessions


def _manifest(root: Path, sha256: str) -> dict[str, object]:
    return json.loads(_manifest_path(root, sha256).read_bytes())


def _table_object_sha256s(
    root: Path,
    generation: dict[str, object],
    table_name: str,
) -> list[str]:
    table_reference = next(
        reference for reference in generation["tables"] if reference["name"] == table_name
    )
    table_manifest = _manifest(root, table_reference["manifest_sha256"])
    return [str(reference["sha256"]) for reference in table_manifest["objects"]]


def _family_table_object_sha256s(
    root: Path,
    generation: dict[str, object],
    family_id: str,
    table_name: str,
) -> list[str]:
    family_reference = next(
        reference for reference in generation["families"] if reference["family_id"] == family_id
    )
    family_manifest = _manifest(root, family_reference["manifest_sha256"])
    return _table_object_sha256s(root, family_manifest, table_name)


def _manifest_path(root: Path, sha256: str) -> Path:
    return root / "manifests" / "sha256" / sha256[:2] / f"{sha256}.json"


def _object_path(root: Path, sha256: str) -> Path:
    return root / "objects" / "sha256" / sha256[:2] / f"{sha256}.parquet"


def _write_manifest(root: Path, value: dict[str, object]) -> tuple[str, bytes]:
    content = canonical_json_bytes(value)
    sha256 = hashlib.sha256(content).hexdigest()
    path = _manifest_path(root, sha256)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return sha256, content


def _replace_family_manifest(
    storage_root: Path,
    candidate_root: dict[str, object],
    family_index: int,
    family_manifest: dict[str, object],
) -> None:
    sha256, content = _write_manifest(storage_root, family_manifest)
    reference = candidate_root["families"][family_index]
    reference["manifest_sha256"] = sha256
    reference["manifest_byte_count"] = len(content)


def _write_candidate_root(storage_root: Path, root: dict[str, object]) -> str:
    identity = {
        "schema_contract": root["schema_contract"],
        "data_through_session": root["data_through_session"],
        "research_sessions": root["research_sessions"],
        "field_availability": root["field_availability"],
        "families": root["families"],
        "financial_research_readiness": root["financial_research_readiness"],
    }
    root["data_identity"] = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    sha256, _ = _write_manifest(storage_root, root)
    return sha256
