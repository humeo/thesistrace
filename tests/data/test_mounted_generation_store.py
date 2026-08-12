from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pytest

from thesistrace.data.generation_files import AddressedFileError, AddressedFileStore
from thesistrace.data.generation_store import (
    GENERATION_MANIFEST_MAX_BYTES,
    GENERATION_SESSION_PARTITION_COUNT,
    GenerationFileRef,
    GenerationStoreError,
    MountedGenerationStore,
)
from thesistrace.publication.serialization import (
    ParquetWriterContract,
    canonical_json_bytes,
    parquet_bytes,
)


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
    reopened = MountedGenerationStore(tmp_path).open_generation(materialized.manifest_sha256)

    assert reopened.manifest_sha256 == materialized.manifest_sha256
    assert reopened.data_identity == materialized.data_identity
    assert reopened.dataset_coverage == {
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
    assert reopened.canonical == canonical

    root = _manifest(tmp_path, materialized.manifest_sha256)
    assert len(canonical_json_bytes(root)) <= GENERATION_MANIFEST_MAX_BYTES
    assert root["schema_contract"] == "canonical-eod"
    assert "st_designations" not in {table["name"] for table in root["tables"]}
    price_table = next(table for table in root["tables"] if table["name"] == "prices")
    price_manifest = _manifest(tmp_path, price_table["manifest_sha256"])
    assert len(canonical_json_bytes(price_manifest)) <= GENERATION_MANIFEST_MAX_BYTES
    assert len(price_manifest["objects"]) == 2
    assert price_manifest["partitioning"] == {
        "kind": "research-session-block",
        "session_count": GENERATION_SESSION_PARTITION_COUNT,
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
    assert (
        MountedGenerationStore(tmp_path).open_generation(second.manifest_sha256).canonical
        == canonical
    )


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
    current_prices = _table_object_sha256s(tmp_path, current_root, "prices")
    candidate_prices = _table_object_sha256s(tmp_path, candidate_root, "prices")
    assert len(set(candidate_prices) - set(current_prices)) == 1
    assert candidate_prices[:-1] == current_prices[:-1]

    reopened = store.open_generation(candidate.manifest_sha256)
    expected = copy.deepcopy(canonical)
    expected["prices"][-1]["turnover_cny"] = "999999.00"
    assert reopened.canonical == expected


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
    price_reference = next(
        reference for reference in root["tables"] if reference["name"] == "prices"
    )
    price_manifest = _manifest(tmp_path, price_reference["manifest_sha256"])
    _object_path(tmp_path, price_manifest["objects"][0]["sha256"]).unlink()

    admission = MountedGenerationStore(tmp_path).open_admission(generation.manifest_sha256)

    assert admission.generation.manifest_sha256 == generation.manifest_sha256
    assert admission.generation.dataset_coverage == {
        "start": canonical["research_calendar"][0],
        "end": canonical["research_calendar"][-1],
        "session_count": len(canonical["research_calendar"]),
    }
    assert admission.generation.field_availability == (
        "market.turnover.cny",
        "price.close.adjusted",
    )
    assert admission.research_calendar == tuple(canonical["research_calendar"])
    assert store.count_universe_instruments(
        generation.manifest_sha256,
        universe="top3000",
        start_session=str(canonical["research_calendar"][0]),
        end_session=str(canonical["research_calendar"][-1]),
    ) == len(
        {
            str(instrument_id)
            for row in canonical["liquidity_universes"]["top3000"]
            for instrument_id in row["instrument_ids"]
        }
    )
    with pytest.raises(GenerationStoreError, match="missing"):
        MountedGenerationStore(tmp_path).open_generation(generation.manifest_sha256)


def test_universe_count_opens_only_overlapping_session_partitions(
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
    original = store._open_partition

    def record_partition(spec, object_ref, ordinal):
        if spec.name == "liquidity_universes":
            opened.append(ordinal)
        return original(spec, object_ref, ordinal)

    monkeypatch.setattr(store, "_open_partition", record_partition)
    final_session = str(canonical["research_calendar"][-1])

    assert (
        store.count_universe_instruments(
            generation.manifest_sha256,
            universe="top3000",
            start_session=final_session,
            end_session=final_session,
        )
        == 2
    )
    assert opened == [2]


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
    table = _manifest(tmp_path, root["tables"][0]["manifest_sha256"])
    object_sha256 = table["objects"][0]["sha256"]
    object_path = _object_path(tmp_path, object_sha256)
    if damage == "missing":
        object_path.unlink()
    else:
        object_path.write_bytes(b"corrupt")

    with pytest.raises(GenerationStoreError, match="missing|checksum|byte count"):
        MountedGenerationStore(tmp_path).open_generation(generation.manifest_sha256)

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
        store.open_generation(generation.manifest_sha256)

    incompatible = canonical_json_bytes(
        {"format": "thesistrace-canonical-generation", "version": 2}
    )
    incompatible_sha256 = hashlib.sha256(incompatible).hexdigest()
    incompatible_path = _manifest_path(tmp_path, incompatible_sha256)
    incompatible_path.parent.mkdir(parents=True, exist_ok=True)
    incompatible_path.write_bytes(incompatible)
    with pytest.raises(GenerationStoreError, match="incompatible"):
        store.open_generation(incompatible_sha256)


def test_incompatible_parquet_schema_is_rejected_even_with_consistent_hashes(
    tmp_path: Path,
) -> None:
    store = MountedGenerationStore(tmp_path)
    generation = store.materialize(
        _canonical(),
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )
    root = _manifest(tmp_path, generation.manifest_sha256)
    table_ref = root["tables"][0]
    table = _manifest(tmp_path, table_ref["manifest_sha256"])
    wrong_contract = ParquetWriterContract(
        name="incompatible-generation-test",
        version=1,
        schema=pa.schema([pa.field("session", pa.int64(), nullable=False)]),
        sort_keys=("session",),
    )
    wrong_rows = [{"session": index} for index in range(GENERATION_SESSION_PARTITION_COUNT)]
    wrong_object = parquet_bytes(wrong_rows, wrong_contract)
    wrong_object_sha256 = hashlib.sha256(wrong_object).hexdigest()
    wrong_object_path = _object_path(tmp_path, wrong_object_sha256)
    wrong_object_path.parent.mkdir(parents=True, exist_ok=True)
    wrong_object_path.write_bytes(wrong_object)
    table["objects"][0].update(
        {
            "sha256": wrong_object_sha256,
            "byte_count": len(wrong_object),
            "row_count": len(wrong_rows),
            "first_sort_key": [0],
            "last_sort_key": [GENERATION_SESSION_PARTITION_COUNT - 1],
        }
    )
    table_sha256, table_bytes = _write_manifest(tmp_path, table)
    table_ref.update({"manifest_sha256": table_sha256, "manifest_byte_count": len(table_bytes)})
    identity = {
        key: root[key]
        for key in (
            "schema_contract",
            "dataset_coverage",
            "data_through_session",
            "field_availability",
            "tables",
        )
    }
    root["data_identity"] = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    root_sha256, _ = _write_manifest(tmp_path, root)

    with pytest.raises(GenerationStoreError, match="schema is incompatible"):
        store.open_generation(root_sha256)


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
        MountedGenerationStore(tmp_path).open_generation(oversized_sha256)

    store = MountedGenerationStore(tmp_path)
    generation = store.materialize(
        _canonical(),
        prepared_at=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        source_name="deterministic-test",
        source_lineage={"snapshot": "fixed"},
    )
    root = _manifest(tmp_path, generation.manifest_sha256)
    table = _manifest(tmp_path, root["tables"][0]["manifest_sha256"])
    object_path = _object_path(tmp_path, table["objects"][0]["sha256"])
    external = tmp_path / "external.parquet"
    external.write_bytes(object_path.read_bytes())
    object_path.unlink()
    object_path.symlink_to(external)
    with pytest.raises(GenerationStoreError, match="unsafe"):
        store.open_generation(generation.manifest_sha256)


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
    table = _manifest(tmp_path, root["tables"][0]["manifest_sha256"])
    object_path = _object_path(tmp_path, table["objects"][0]["sha256"])
    object_path.unlink()
    os.mkfifo(object_path)

    with pytest.raises(GenerationStoreError, match="regular file"):
        store.open_generation(generation.manifest_sha256)


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
    assert (
        MountedGenerationStore(tmp_path).open_generation(manifest_sha256).canonical == _canonical()
    )


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
                    "turnover_cny": str(raw * 10000),
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
