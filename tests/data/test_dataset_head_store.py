from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(move, candidates))

    assert outcomes.count("conflict") == 1
    winner = next(outcome for outcome in outcomes if outcome != "conflict")
    current = MountedDatasetHeadStore(tmp_path).current()
    assert current is not None and current.generation_manifest_sha256 == winner
    assert current.generation.canonical == build_minimal_canonical_fixture()


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


def _materialize(store: MountedGenerationStore, *, ordinal: int) -> str:
    generation = store.materialize(
        build_minimal_canonical_fixture(),
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC) + timedelta(minutes=ordinal),
        source_name="head-store-test",
        source_lineage={"candidate": ordinal},
    )
    return generation.manifest_sha256
