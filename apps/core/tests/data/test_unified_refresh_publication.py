from datetime import UTC, datetime

import pytest

from thesistrace.benchmark import BenchmarkLevel
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.data.head_store import DatasetHeadConflict, MountedDatasetHeadStore
from thesistrace.fixture import build_minimal_canonical_fixture


def test_prepared_benchmark_is_invisible_until_the_dataset_head_commits(tmp_path):
    from thesistrace.data.benchmark_snapshot import (
        PreparedBenchmarkSnapshots,
        PublishedBenchmarkSnapshots,
    )

    data = tmp_path / "data"
    benchmark = tmp_path / "benchmark"
    snapshots = PreparedBenchmarkSnapshots(benchmark)
    reader = PublishedBenchmarkSnapshots(benchmark, data)
    store = MountedGenerationStore(data)
    generation = store.materialize(
        build_minimal_canonical_fixture(),
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
        source_name="test",
        source_lineage={"fixture": "atomic-refresh"},
    )
    heads = MountedDatasetHeadStore(data)
    old = snapshots.prepare(
        [BenchmarkLevel("2010-01-04", "3500")],
        published_at=datetime(2026, 8, 9, tzinfo=UTC),
    )
    with heads.resolved_pointer_candidate(generation.manifest_sha256) as candidate:
        heads.compare_and_swap_pointer_resolved(
            expected_generation_manifest_sha256=None,
            candidate=candidate,
            benchmark_snapshot_sha256=old.sha256,
        )
    prepared = snapshots.prepare(
        [BenchmarkLevel("2010-01-04", "3500"), BenchmarkLevel("2010-01-05", "3520")],
        published_at=datetime(2026, 8, 10, tzinfo=UTC),
    )

    assert reader.read() == old
    with heads.resolved_pointer_candidate(generation.manifest_sha256) as candidate:
        with pytest.raises(DatasetHeadConflict):
            heads.compare_and_swap_pointer_resolved(
                expected_generation_manifest_sha256="0" * 64,
                candidate=candidate,
                benchmark_snapshot_sha256=prepared.sha256,
            )
    assert reader.read() == old

    with heads.resolved_pointer_candidate(generation.manifest_sha256) as candidate:
        published = heads.compare_and_swap_pointer_resolved(
            expected_generation_manifest_sha256=generation.manifest_sha256,
            candidate=candidate,
            benchmark_snapshot_sha256=prepared.sha256,
        )
    assert reader.read() == prepared
    assert heads.resolve_descriptor(published).manifest_sha256 == generation.manifest_sha256


def test_head_upgrade_preserves_data_and_old_benchmark_and_can_resume(tmp_path, monkeypatch):
    import json

    import thesistrace.migrations.unified_refresh_0006 as migration
    from thesistrace.benchmark import BenchmarkSnapshotStore
    from thesistrace.data.benchmark_snapshot import PublishedBenchmarkSnapshots
    from thesistrace.publication.serialization import canonical_json_bytes

    data, benchmark, backup = (tmp_path / name for name in ("data", "benchmark", "backup"))
    generation = MountedGenerationStore(data).materialize(
        build_minimal_canonical_fixture(),
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
        source_name="fixture",
        source_lineage={"fixture": "upgrade"},
    )
    heads = MountedDatasetHeadStore(data)
    with heads.resolved_pointer_candidate(generation.manifest_sha256) as candidate:
        heads.compare_and_swap_pointer_resolved(
            expected_generation_manifest_sha256=None, candidate=candidate
        )
    source = json.loads((data / "HEAD.json").read_bytes())
    source["version"] = 1
    del source["benchmark_snapshot_sha256"]
    original = canonical_json_bytes(source)
    (data / "HEAD.json").write_bytes(original)
    old = BenchmarkSnapshotStore(benchmark).publish(
        [BenchmarkLevel("2010-01-04", "3500")],
        published_at=datetime(2026, 8, 9, tzinfo=UTC),
    )
    assert migration.migrate_head(data, benchmark, backup=backup)["status"] == "validated"
    assert (data / "HEAD.json").read_bytes() == original

    def interrupted(*_args):
        raise OSError("injected before atomic replacement")

    with monkeypatch.context() as patch:
        patch.setattr(migration, "_replace_entry", interrupted)
        with pytest.raises(OSError, match="injected"):
            migration.migrate_head(data, benchmark, backup=backup, apply=True)
    assert (data / "HEAD.json").read_bytes() == original
    assert (backup / "HEAD.v1.json").read_bytes() == original
    assert migration.migrate_head(data, benchmark, backup=backup, apply=True)["status"] == "applied"
    assert heads.current_pointer().generation_manifest_sha256 == generation.manifest_sha256
    assert PublishedBenchmarkSnapshots(benchmark, data).read() == old
    assert (
        migration.migrate_head(data, benchmark, backup=backup, apply=True)["status"]
        == "already_current"
    )
