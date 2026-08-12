from datetime import UTC, datetime
from pathlib import Path

import pytest

from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.data.head_store import DatasetHeadConflict, MountedDatasetHeadStore
from thesistrace.fixture import build_minimal_canonical_fixture


def test_head_cas_publishes_only_a_validated_family_root(tmp_path: Path) -> None:
    generation = MountedGenerationStore(tmp_path).materialize(
        build_minimal_canonical_fixture(),
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
        source_name="test",
        source_lineage={"fixture": "head"},
    )
    heads = MountedDatasetHeadStore(tmp_path)

    with heads.resolved_pointer_candidate(generation.manifest_sha256) as candidate:
        published = heads.compare_and_swap_pointer_resolved(
            expected_generation_manifest_sha256=None,
            candidate=candidate,
        )

    assert heads.current_pointer() == published
    assert heads.resolve_descriptor(published).manifest_sha256 == generation.manifest_sha256


def test_head_cas_rejects_stale_expected_root(tmp_path: Path) -> None:
    store = MountedGenerationStore(tmp_path)
    generation = store.materialize(
        build_minimal_canonical_fixture(),
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
        source_name="test",
        source_lineage={"fixture": "head"},
    )
    heads = MountedDatasetHeadStore(tmp_path)
    with heads.resolved_pointer_candidate(generation.manifest_sha256) as candidate:
        heads.compare_and_swap_pointer_resolved(
            expected_generation_manifest_sha256=None,
            candidate=candidate,
        )
    with heads.resolved_pointer_candidate(generation.manifest_sha256) as candidate:
        with pytest.raises(DatasetHeadConflict):
            heads.compare_and_swap_pointer_resolved(
                expected_generation_manifest_sha256="0" * 64,
                candidate=candidate,
            )
