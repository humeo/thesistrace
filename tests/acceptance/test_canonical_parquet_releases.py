import json
from pathlib import Path

from thesistrace.datasets import DatasetPublisher
from thesistrace.fixture import build_fixture
from thesistrace.objects import ImmutableObjectStore
from thesistrace.storage import MetadataStore


def test_bootstrap_publishes_canonical_families_as_manifest_bound_parquet(
    tmp_path: Path,
) -> None:
    source, canonical = build_fixture()
    publisher, objects = publisher_at(tmp_path)

    release, created = publisher.bootstrap_documents(
        "root",
        source=source,
        canonical=canonical,
        source_kind="source_fixture",
        source_schema="tushare-fixture-v1",
    )

    assert created is True
    assert canonical_semantics(publisher.materialize_canonical(release)) == canonical_semantics(
        canonical
    )
    assert not {
        entry["kind"]
        for entry in release["objects"]
        if isinstance(entry, dict)
    } & {"canonical_fixture", "canonical_delta"}
    canonical_entries = canonical_partitions(release)
    assert {entry["family"] for entry in canonical_entries} == {
        "canonical.field_catalog",
        "equity.adjustment_anchor",
        "equity.eod_price",
        "equity.industry_sw2021",
        "equity.liquidity_universe",
        "equity.price_limit",
        "equity.trading_state",
        "instrument.identity",
        "market.research_calendar",
        "universe.base_pool",
    }
    for entry in canonical_entries:
        assert entry["format"] == "parquet"
        assert entry["schema_version"]
        assert entry["partition"]
        assert entry["writer_contract_id"]
        assert entry["bytes"] > 0
        assert len(entry["sha256"]) == 64
        assert objects.parquet_path_for(entry["sha256"]).stat().st_size == entry["bytes"]

    source_entry = next(entry for entry in release["objects"] if entry["kind"] == "source_fixture")
    assert objects.path_for(source_entry["sha256"]).is_file()


def test_one_session_increment_reuses_every_historical_canonical_partition(
    tmp_path: Path,
) -> None:
    publisher, _objects = publisher_at(tmp_path)
    root, _ = publisher.bootstrap("root", "v1")

    release, created = publisher.publish_fixture_increment(
        "next-session",
        new_sessions=1,
        corrections=[],
    )

    assert created is True
    root_entries = {partition_identity(entry) for entry in canonical_partitions(root)}
    next_entries = {partition_identity(entry) for entry in canonical_partitions(release)}
    assert root_entries < next_entries
    appended = [
        entry
        for entry in canonical_partitions(release)
        if partition_identity(entry) not in root_entries
    ]
    assert {entry["family"] for entry in appended} == {
        "equity.eod_price",
        "equity.liquidity_universe",
        "equity.price_limit",
        "equity.trading_state",
        "market.research_calendar",
        "universe.base_pool",
    }
    assert all(
        entry["partition"]["start"] == release["appended_session_range"]["start"]
        and entry["partition"]["end"] == release["appended_session_range"]["end"]
        for entry in appended
    )
    assert not any(
        entry["kind"] == "canonical_delta"
        for entry in release["objects"]
        if isinstance(entry, dict)
    )
    assert publisher.materialize_canonical(release)["research_calendar"][-1] == release[
        "appended_session_range"
    ]["end"]


def test_correction_replaces_only_affected_partitions_and_preserves_other_identities(
    tmp_path: Path,
) -> None:
    publisher, _objects = publisher_at(tmp_path)
    root, _ = publisher.bootstrap("root", "v1")
    daily, _ = publisher.publish_fixture_increment(
        "daily",
        new_sessions=1,
        corrections=[],
    )
    correction = {
        "session": root["appended_session_range"]["start"],
        "instrument_id": "equity:600000.SH",
        "field": "close_raw",
        "value": "8.0500",
    }

    corrected, created = publisher.publish_fixture_increment(
        "corrected",
        new_sessions=1,
        corrections=[correction],
    )

    assert created is True
    assert corrected["correction_change_set"] == [correction]
    previous_by_family = partitions_by_family(daily)
    corrected_by_family = partitions_by_family(corrected)
    for family in {
        "canonical.field_catalog",
        "equity.adjustment_anchor",
        "equity.industry_sw2021",
        "instrument.identity",
    }:
        assert corrected_by_family[family] == previous_by_family[family]
    for family in {
        "equity.price_limit",
        "equity.trading_state",
        "market.research_calendar",
        "universe.base_pool",
    }:
        assert previous_by_family[family] < corrected_by_family[family]

    previous_price_by_partition = {
        json.dumps(entry["partition"], sort_keys=True): entry["sha256"]
        for entry in canonical_partitions(daily)
        if entry["family"] == "equity.eod_price"
    }
    corrected_price_by_partition = {
        json.dumps(entry["partition"], sort_keys=True): entry["sha256"]
        for entry in canonical_partitions(corrected)
        if entry["family"] == "equity.eod_price"
    }
    root_partition = json.dumps(
        {
            "type": "session_range",
            "start": root["appended_session_range"]["start"],
            "end": root["appended_session_range"]["end"],
        },
        sort_keys=True,
    )
    assert previous_price_by_partition[root_partition] != corrected_price_by_partition[
        root_partition
    ]
    materialized = publisher.materialize_canonical(corrected)
    corrected_row = next(
        row
        for row in materialized["prices"]
        if row["session"] == correction["session"]
        and row["instrument_id"] == correction["instrument_id"]
    )
    assert corrected_row["close_raw"] == "8.0500"


def test_legacy_nested_canonical_release_remains_readable(tmp_path: Path) -> None:
    _source, canonical = build_fixture()
    publisher, objects = publisher_at(tmp_path)
    canonical_object = objects.put_json(canonical)
    legacy_release = {
        "id": "dsr_legacy",
        "objects": [{"kind": "canonical_fixture", **canonical_object}],
    }

    assert publisher.materialize_canonical(legacy_release) == canonical


def test_next_publication_migrates_a_legacy_predecessor_without_rewriting_json(
    tmp_path: Path,
) -> None:
    source, canonical = build_fixture()
    publisher, objects = publisher_at(tmp_path)
    source_object = objects.put_json(source)
    canonical_object = objects.put_json(canonical)
    legacy_release = {
        "id": "dsr_legacy",
        "predecessor_id": None,
        "created_at": "2026-07-30T00:00:00+00:00",
        "appended_session_range": {
            "start": canonical["research_calendar"][0],
            "end": canonical["research_calendar"][-1],
        },
        "session_count": 756,
        "instrument_count": len(canonical["instruments"]),
        "correction_change_set": [],
        "schemas": [
            {"family": "source_fixture", "version": "tushare-fixture-v1"},
            {"family": "canonical_eod", "version": "canonical-eod-v1"},
        ],
        "objects": [
            {"kind": "source_fixture", **source_object},
            {"kind": "canonical_fixture", **canonical_object},
        ],
        "manifest_sha256": "legacy",
    }
    publisher.metadata.publish_dataset_release(legacy_release, "legacy-root")

    migrated, created = publisher.publish_fixture_increment(
        "migrate",
        new_sessions=1,
        corrections=[],
    )

    assert created is True
    assert not any(
        entry["kind"] in {"canonical_fixture", "canonical_delta"}
        for entry in migrated["objects"]
    )
    partitions = canonical_partitions(migrated)
    assert partitions
    schemas = {
        str(item["family"]): str(item["version"])
        for item in migrated["schemas"]
    }
    assert all(
        schemas[str(entry["family"])] == entry["schema_version"]
        for entry in partitions
    )
    assert publisher.materialize_canonical(migrated)["research_calendar"][-1] == migrated[
        "appended_session_range"
    ]["end"]


def publisher_at(tmp_path: Path) -> tuple[DatasetPublisher, ImmutableObjectStore]:
    metadata = MetadataStore(tmp_path / "metadata.sqlite3")
    metadata.initialize()
    objects = ImmutableObjectStore(tmp_path / "objects")
    return DatasetPublisher(metadata, objects), objects


def canonical_partitions(release: dict[str, object]) -> list[dict[str, object]]:
    objects = release["objects"]
    assert isinstance(objects, list)
    return [
        entry
        for entry in objects
        if isinstance(entry, dict) and entry.get("kind") == "canonical_partition"
    ]


def partition_identity(entry: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(entry["family"]),
        json.dumps(entry["partition"], sort_keys=True),
        str(entry["sha256"]),
    )


def partitions_by_family(
    release: dict[str, object],
) -> dict[str, set[tuple[str, str, str]]]:
    grouped: dict[str, set[tuple[str, str, str]]] = {}
    for entry in canonical_partitions(release):
        grouped.setdefault(str(entry["family"]), set()).add(partition_identity(entry))
    return grouped


def canonical_semantics(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): canonical_semantics(item)
            for key, item in sorted(value.items())
        }
    if isinstance(value, list):
        normalized = [canonical_semantics(item) for item in value]
        if all(isinstance(item, dict) for item in normalized):
            return sorted(
                normalized,
                key=lambda item: json.dumps(item, sort_keys=True),
            )
        return normalized
    return value
