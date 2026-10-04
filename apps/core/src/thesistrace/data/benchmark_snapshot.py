"""Immutable Benchmark Snapshots selected by the accepted Dataset Head."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from thesistrace.benchmark.snapshot import (
    BenchmarkLevel,
    BenchmarkSnapshot,
    BenchmarkSnapshotError,
    _decode_snapshot,
    encode_benchmark_snapshot,
    validate_independent_benchmark_mount,
)


class PreparedBenchmarkSnapshots:
    def __init__(self, root: Path | str) -> None:
        from thesistrace.data.generation_files import AddressedFileStore

        self._root = Path(root)
        self._files = AddressedFileStore(self._root)

    def prepare(
        self,
        levels: Sequence[BenchmarkLevel],
        *,
        published_at: datetime,
    ) -> BenchmarkSnapshot:
        content = encode_benchmark_snapshot(levels, published_at=published_at)
        digest = hashlib.sha256(content).hexdigest()
        self._root.mkdir(parents=True, exist_ok=True)
        self._files.store(self._path(digest), digest, content)
        return _decode_snapshot(content)

    def read(self, digest: str) -> BenchmarkSnapshot:
        from thesistrace.data.generation_files import AddressedFileError

        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise BenchmarkSnapshotError("BENCHMARK_SNAPSHOT_IDENTITY_INVALID")
        try:
            content = self._files.read(self._path(digest), digest, max_byte_count=8 * 1024 * 1024)
        except AddressedFileError as error:
            raise BenchmarkSnapshotError("BENCHMARK_SNAPSHOT_UNREADABLE") from error
        return _decode_snapshot(content)

    def _path(self, digest: str) -> Path:
        return self._root / "snapshots" / f"{digest}.json"


class PublishedBenchmarkSnapshots:
    def __init__(self, root: Path | str, data_root: Path | str) -> None:
        from thesistrace.data.head_store import MountedDatasetHeadStore

        self._snapshots = PreparedBenchmarkSnapshots(
            validate_independent_benchmark_mount(data_root, root)
        )
        self._heads = MountedDatasetHeadStore(data_root)

    def read(self) -> BenchmarkSnapshot | None:
        from thesistrace.data.head_store import DatasetHeadError

        try:
            head = self._heads.current_pointer()
        except DatasetHeadError as error:
            raise BenchmarkSnapshotError("BENCHMARK_PUBLICATION_UNAVAILABLE") from error
        if head is None or head.benchmark_snapshot_sha256 is None:
            return None
        return self._snapshots.read(head.benchmark_snapshot_sha256)


class BenchmarkSnapshotPreparation:
    """Updater destination whose writes remain invisible until Dataset Head moves."""

    def __init__(self, root: Path | str, data_root: Path | str) -> None:
        self._published = PublishedBenchmarkSnapshots(root, data_root)
        self._prepared = PreparedBenchmarkSnapshots(root)

    def read(self) -> BenchmarkSnapshot | None:
        return self._published.read()

    def publish(
        self, levels: Sequence[BenchmarkLevel], *, published_at: datetime
    ) -> BenchmarkSnapshot:
        return self._prepared.prepare(levels, published_at=published_at)
