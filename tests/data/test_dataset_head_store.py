from __future__ import annotations

import fcntl
import os
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from thesistrace.data import (
    DatasetHeadConflict,
    DatasetHeadError,
    MountedDatasetHeadStore,
    MountedGenerationStore,
)
from thesistrace.fixture import build_minimal_canonical_fixture


def test_empty_store_and_atomic_compare_and_swap_survive_restart(tmp_path: Path) -> None:
    generations = MountedGenerationStore(tmp_path)
    first = _materialize(generations, ordinal=1)
    second = _materialize(generations, ordinal=2)
    heads = MountedDatasetHeadStore(tmp_path)

    assert heads.current() is None
    established = heads.compare_and_swap(
        expected_generation_manifest_sha256=None,
        candidate_generation_manifest_sha256=first,
    )
    assert established.generation_manifest_sha256 == first
    assert established.dataset_coverage == {
        "start": "2026-08-07",
        "end": "2026-08-07",
        "session_count": 1,
    }
    assert established.data_through_session == "2026-08-07"

    with pytest.raises(DatasetHeadConflict):
        heads.compare_and_swap(
            expected_generation_manifest_sha256=None,
            candidate_generation_manifest_sha256=second,
        )
    assert MountedDatasetHeadStore(tmp_path).current() == established

    moved = MountedDatasetHeadStore(tmp_path).compare_and_swap(
        expected_generation_manifest_sha256=first,
        candidate_generation_manifest_sha256=second,
    )
    reopened = MountedDatasetHeadStore(tmp_path).current()
    assert reopened == moved
    assert reopened is not None and reopened.prepared_at == "2026-08-09T00:02:00+00:00"


def test_concurrent_head_movers_cannot_both_win(tmp_path: Path) -> None:
    generations = MountedGenerationStore(tmp_path)
    original = _materialize(generations, ordinal=1)
    candidates = (_materialize(generations, ordinal=2), _materialize(generations, ordinal=3))
    MountedDatasetHeadStore(tmp_path).compare_and_swap(
        expected_generation_manifest_sha256=None,
        candidate_generation_manifest_sha256=original,
    )

    def move(candidate: str) -> str:
        try:
            MountedDatasetHeadStore(tmp_path).compare_and_swap(
                expected_generation_manifest_sha256=original,
                candidate_generation_manifest_sha256=candidate,
            )
        except DatasetHeadConflict:
            return "conflict"
        return candidate

    lock_descriptor = os.open(tmp_path / ".head.lock", os.O_RDWR)
    fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
    executor = ThreadPoolExecutor(max_workers=2)
    try:
        futures = tuple(executor.submit(move, candidate) for candidate in candidates)
        _, blocked = wait(futures, timeout=0.2)
        assert len(blocked) == 2
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        outcomes = tuple(future.result(timeout=10) for future in futures)
    finally:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)
        executor.shutdown(wait=True)

    assert outcomes.count("conflict") == 1
    winner = next(outcome for outcome in outcomes if outcome != "conflict")
    current = MountedDatasetHeadStore(tmp_path).current()
    assert current is not None and current.generation_manifest_sha256 == winner
    expected_offset = candidates.index(winner) + 2
    assert current.generation.canonical == build_minimal_canonical_fixture(
        price_offset=expected_offset
    )
    assert (
        len(
            {
                MountedGenerationStore(tmp_path).open_generation(candidate).data_identity
                for candidate in candidates
            }
        )
        == 2
    )


def test_invalid_candidate_or_malformed_head_is_never_served(tmp_path: Path) -> None:
    first = _materialize(MountedGenerationStore(tmp_path), ordinal=1)
    heads = MountedDatasetHeadStore(tmp_path)
    heads.compare_and_swap(
        expected_generation_manifest_sha256=None,
        candidate_generation_manifest_sha256=first,
    )

    with pytest.raises(RuntimeError, match="missing"):
        heads.compare_and_swap(
            expected_generation_manifest_sha256=first,
            candidate_generation_manifest_sha256="0" * 64,
        )
    assert heads.current() is not None

    (tmp_path / "HEAD.json").write_bytes(b'{"format":')
    with pytest.raises(DatasetHeadError, match="malformed"):
        MountedDatasetHeadStore(tmp_path).current()


def test_resolved_candidate_capability_cannot_cross_mounts(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    source_root.mkdir()
    target_root.mkdir()
    source_store = MountedGenerationStore(source_root)
    manifest = _materialize(source_store, ordinal=1)
    candidate = MountedDatasetHeadStore(source_root).resolve_candidate(manifest)

    with pytest.raises(DatasetHeadError, match="another mounted store"):
        MountedDatasetHeadStore(target_root).compare_and_swap_resolved(
            expected_generation_manifest_sha256=None,
            candidate=candidate,
        )
    assert MountedDatasetHeadStore(target_root).current() is None


def test_resolved_candidate_is_opaque_and_single_use(tmp_path: Path) -> None:
    store = MountedGenerationStore(tmp_path)
    first = _materialize(store, ordinal=1)
    heads = MountedDatasetHeadStore(tmp_path)
    candidate = heads.resolve_candidate(first)

    assert not hasattr(candidate, "generation")
    established = heads.compare_and_swap_resolved(
        expected_generation_manifest_sha256=None,
        candidate=candidate,
    )
    assert established.generation_manifest_sha256 == first
    with pytest.raises(DatasetHeadError, match="another mounted store"):
        heads.compare_and_swap_resolved(
            expected_generation_manifest_sha256=first,
            candidate=candidate,
        )


def test_head_read_stops_at_hard_bound_when_file_grows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head = tmp_path / "HEAD.json"
    head.write_bytes(b"x" * 65_536)
    original_read = os.read
    total_read = 0

    def append_while_reading(descriptor: int, byte_count: int) -> bytes:
        nonlocal total_read
        chunk = original_read(descriptor, byte_count)
        total_read += len(chunk)
        if total_read == 65_536:
            with head.open("ab") as stream:
                stream.write(b"growth-beyond-bound")
        return chunk

    monkeypatch.setattr(os, "read", append_while_reading)
    with pytest.raises(DatasetHeadError, match="byte bound"):
        MountedDatasetHeadStore(tmp_path).current()
    assert total_read == 65_537


@pytest.mark.parametrize("unsafe_kind", ["symlink", "fifo", "oversized"])
def test_unsafe_head_entry_is_rejected_without_blocking(tmp_path: Path, unsafe_kind: str) -> None:
    head = tmp_path / "HEAD.json"
    if unsafe_kind == "symlink":
        target = tmp_path / "target.json"
        target.write_bytes(b"{}")
        head.symlink_to(target)
    elif unsafe_kind == "fifo":
        os.mkfifo(head)
    else:
        head.write_bytes(b"x" * 65_537)

    with pytest.raises(DatasetHeadError, match="read failed|regular file|byte bound"):
        MountedDatasetHeadStore(tmp_path).current()


def _materialize(store: MountedGenerationStore, *, ordinal: int) -> str:
    generation = store.materialize(
        build_minimal_canonical_fixture(price_offset=ordinal),
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC) + timedelta(minutes=ordinal),
        source_name="head-store-test",
        source_lineage={"candidate": ordinal},
    )
    return generation.manifest_sha256
