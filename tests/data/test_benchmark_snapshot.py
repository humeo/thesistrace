from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

import thesistrace.benchmark.snapshot as snapshot_module
from thesistrace.benchmark import (
    BENCHMARK_SNAPSHOT_FILENAME,
    BenchmarkLevel,
    BenchmarkSnapshotError,
    BenchmarkSnapshotStore,
    BenchmarkSnapshotUpdater,
)

PUBLISHED_AT = datetime(2026, 8, 27, 10, tzinfo=UTC)


class RecordingSource:
    def __init__(self, responses: list[tuple[BenchmarkLevel, ...]]) -> None:
        self._responses = iter(responses)
        self.requests: list[tuple[str, str]] = []

    def collect_open_levels(
        self,
        *,
        start_session: str,
        end_session: str,
    ) -> tuple[BenchmarkLevel, ...]:
        self.requests.append((start_session, end_session))
        return next(self._responses)


def test_first_update_publishes_strict_complete_snapshot(tmp_path: Path) -> None:
    source = RecordingSource(
        [
            (
                BenchmarkLevel("2010-01-04", "3592.47"),
                BenchmarkLevel("2010-01-05", "3545.19"),
                BenchmarkLevel("2010-01-06", "3558.7"),
            )
        ]
    )
    store = BenchmarkSnapshotStore(tmp_path)

    result = BenchmarkSnapshotUpdater(
        store,
        source,
        clock=lambda: PUBLISHED_AT,
    ).update(("2010-01-04", "2010-01-05", "2010-01-06"))

    assert result.published is True
    assert source.requests == [("2010-01-04", "2010-01-06")]
    assert result.snapshot == store.read()
    raw = json.loads((tmp_path / BENCHMARK_SNAPSHOT_FILENAME).read_bytes())
    assert set(raw) == {
        "format",
        "version",
        "contract_version",
        "benchmark",
        "source",
        "published_at",
        "coverage",
        "levels",
    }
    assert raw["benchmark"] == {
        "id": "csi300-price-index-open",
        "display_name": "沪深300",
        "ts_code": "399300.SZ",
        "kind": "price_index",
        "coordinate": "open",
    }
    assert raw["coverage"] == {
        "start_session": "2010-01-04",
        "end_session": "2010-01-06",
        "session_count": 3,
    }


def test_update_ignores_market_warmup_before_the_fixed_benchmark_start(
    tmp_path: Path,
) -> None:
    source = RecordingSource(
        [
            (
                BenchmarkLevel("2010-01-04", "3592.47"),
                BenchmarkLevel("2010-01-05", "3545.19"),
            )
        ]
    )

    result = BenchmarkSnapshotUpdater(BenchmarkSnapshotStore(tmp_path), source).update(
        ("2009-12-31", "2010-01-04", "2010-01-05")
    )

    assert result.snapshot.coverage_start_session == "2010-01-04"
    assert result.snapshot.coverage_end_session == "2010-01-05"
    assert source.requests == [("2010-01-04", "2010-01-05")]


def test_update_requests_only_new_dates_and_never_overwrites_history(tmp_path: Path) -> None:
    store = BenchmarkSnapshotStore(tmp_path)
    store.publish(
        (
            BenchmarkLevel("2010-01-04", "3592.47"),
            BenchmarkLevel("2010-01-05", "3545.19"),
        ),
        published_at=PUBLISHED_AT,
    )
    source = RecordingSource(
        [
            (
                BenchmarkLevel("2010-01-06", "3558.7"),
                BenchmarkLevel("2010-01-07", "3543.16"),
            )
        ]
    )

    result = BenchmarkSnapshotUpdater(
        store,
        source,
        clock=lambda: datetime(2026, 8, 28, tzinfo=UTC),
    ).update(("2010-01-04", "2010-01-05", "2010-01-06", "2010-01-07"))

    assert source.requests == [("2010-01-06", "2010-01-07")]
    assert [level.open_level for level in result.snapshot.levels] == [
        "3592.47",
        "3545.19",
        "3558.7",
        "3543.16",
    ]


def test_update_is_idempotent_when_snapshot_already_covers_target(tmp_path: Path) -> None:
    store = BenchmarkSnapshotStore(tmp_path)
    original = store.publish(
        (
            BenchmarkLevel("2010-01-04", "3592.47"),
            BenchmarkLevel("2010-01-05", "3545.19"),
        ),
        published_at=PUBLISHED_AT,
    )
    source = RecordingSource([])

    result = BenchmarkSnapshotUpdater(store, source).update(("2010-01-04", "2010-01-05"))

    assert result == snapshot_module.BenchmarkSnapshotUpdate(original, False)
    assert source.requests == []


@pytest.mark.parametrize(
    ("levels", "code"),
    [
        (
            (
                BenchmarkLevel("2010-01-05", "3545.19"),
                BenchmarkLevel("2010-01-05", "3545.2"),
            ),
            "BENCHMARK_SESSIONS_NOT_STRICTLY_ORDERED",
        ),
        (
            (
                BenchmarkLevel("2010-01-05", "3545.19"),
                BenchmarkLevel("2010-01-06", "NaN"),
            ),
            "BENCHMARK_LEVEL_INVALID",
        ),
        (
            (
                BenchmarkLevel("2010-01-05", "3545.19"),
                BenchmarkLevel("2010-01-06", "0"),
            ),
            "BENCHMARK_LEVEL_INVALID",
        ),
    ],
)
def test_invalid_new_levels_leave_existing_snapshot_unchanged(
    tmp_path: Path,
    levels: tuple[BenchmarkLevel, ...],
    code: str,
) -> None:
    store = BenchmarkSnapshotStore(tmp_path)
    original = store.publish(
        (BenchmarkLevel("2010-01-04", "3592.47"),),
        published_at=PUBLISHED_AT,
    )
    source = RecordingSource([levels])

    with pytest.raises(BenchmarkSnapshotError, match=code):
        BenchmarkSnapshotUpdater(store, source).update(("2010-01-04", "2010-01-06"))

    assert store.read() == original


def test_missing_required_level_rejects_publication(tmp_path: Path) -> None:
    source = RecordingSource(
        [
            (
                BenchmarkLevel("2010-01-04", "3592.47"),
                BenchmarkLevel("2010-01-06", "3558.7"),
            )
        ]
    )

    with pytest.raises(
        BenchmarkSnapshotError,
        match="BENCHMARK_COVERAGE_INSUFFICIENT",
    ):
        BenchmarkSnapshotUpdater(BenchmarkSnapshotStore(tmp_path), source).update(
            ("2010-01-04", "2010-01-05", "2010-01-06")
        )

    assert not (tmp_path / BENCHMARK_SNAPSHOT_FILENAME).exists()


def test_atomic_replace_failure_preserves_previous_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = BenchmarkSnapshotStore(tmp_path)
    original = store.publish(
        (BenchmarkLevel("2010-01-04", "3592.47"),),
        published_at=PUBLISHED_AT,
    )

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("simulated atomic rename failure")

    monkeypatch.setattr(snapshot_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated atomic rename failure"):
        store.publish(
            (
                BenchmarkLevel("2010-01-04", "3592.47"),
                BenchmarkLevel("2010-01-05", "3545.19"),
            ),
            published_at=datetime(2026, 8, 28, tzinfo=UTC),
        )

    assert store.read() == original
    assert list(tmp_path.glob("*.tmp")) == []


def test_precommit_directory_sync_failure_preserves_previous_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = BenchmarkSnapshotStore(tmp_path)
    original = store.publish(
        (BenchmarkLevel("2010-01-04", "3592.47"),),
        published_at=PUBLISHED_AT,
    )
    real_fsync = snapshot_module.os.fsync

    def fail_directory_sync(descriptor: int) -> None:
        if snapshot_module.stat.S_ISDIR(snapshot_module.os.fstat(descriptor).st_mode):
            raise OSError("simulated directory sync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(snapshot_module.os, "fsync", fail_directory_sync)
    with pytest.raises(OSError, match="simulated directory sync failure"):
        store.publish(
            (
                BenchmarkLevel("2010-01-04", "3592.47"),
                BenchmarkLevel("2010-01-05", "3545.19"),
            ),
            published_at=datetime(2026, 8, 28, tzinfo=UTC),
        )

    assert store.read() == original
    assert list(tmp_path.glob("*.tmp")) == []


def test_postrename_directory_sync_failure_rolls_back_previous_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = BenchmarkSnapshotStore(tmp_path)
    original = store.publish(
        (BenchmarkLevel("2010-01-04", "3592.47"),),
        published_at=PUBLISHED_AT,
    )
    real_fsync = snapshot_module.os.fsync
    injected = False

    def fail_postrename_directory_sync(descriptor: int) -> None:
        nonlocal injected
        if (
            not injected
            and snapshot_module.stat.S_ISDIR(snapshot_module.os.fstat(descriptor).st_mode)
            and json.loads(store.path.read_bytes())["coverage"]["end_session"]
            == "2010-01-05"
        ):
            injected = True
            raise OSError("simulated post-rename directory sync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(snapshot_module.os, "fsync", fail_postrename_directory_sync)
    with pytest.raises(OSError, match="simulated post-rename directory sync failure"):
        store.publish(
            (
                BenchmarkLevel("2010-01-04", "3592.47"),
                BenchmarkLevel("2010-01-05", "3545.19"),
            ),
            published_at=datetime(2026, 8, 28, tzinfo=UTC),
        )

    assert store.read() == original
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob("*.rollback")) == []


def test_reader_waits_for_inflight_publication_before_reconciling_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = BenchmarkSnapshotStore(tmp_path)
    store.publish(
        (BenchmarkLevel("2010-01-04", "3592.47"),),
        published_at=PUBLISHED_AT,
    )
    writer_at_replace = threading.Event()
    allow_replace = threading.Event()
    reader_waiting_for_lock = threading.Event()
    reader_done = threading.Event()
    real_replace = snapshot_module.os.replace
    real_flock = snapshot_module.fcntl.flock
    results: dict[str, object] = {}
    errors: list[BaseException] = []

    def pause_writer_replace(source: object, destination: object) -> None:
        if Path(destination) == store.path and Path(source).suffix == ".tmp":
            writer_at_replace.set()
            if not allow_replace.wait(timeout=5):
                raise AssertionError("publication was not released by the test")
        real_replace(source, destination)

    def observe_reader_lock(descriptor: int, operation: int) -> None:
        if threading.current_thread().name == "benchmark-reader":
            reader_waiting_for_lock.set()
        real_flock(descriptor, operation)

    def publish() -> None:
        try:
            results["published"] = store.publish(
                (
                    BenchmarkLevel("2010-01-04", "3592.47"),
                    BenchmarkLevel("2010-01-05", "3545.19"),
                ),
                published_at=datetime(2026, 8, 28, tzinfo=UTC),
            )
        except BaseException as error:
            errors.append(error)

    def read() -> None:
        try:
            results["read"] = BenchmarkSnapshotStore(tmp_path).read()
        except BaseException as error:
            errors.append(error)
        finally:
            reader_done.set()

    monkeypatch.setattr(snapshot_module.os, "replace", pause_writer_replace)
    monkeypatch.setattr(snapshot_module.fcntl, "flock", observe_reader_lock)
    writer = threading.Thread(target=publish, name="benchmark-writer")
    reader = threading.Thread(target=read, name="benchmark-reader")
    writer.start()
    assert writer_at_replace.wait(timeout=5)
    reader.start()
    assert reader_waiting_for_lock.wait(timeout=5)
    assert not reader_done.is_set()

    allow_replace.set()
    writer.join(timeout=5)
    reader.join(timeout=5)

    assert not writer.is_alive()
    assert not reader.is_alive()
    assert errors == []
    published = results["published"]
    observed = results["read"]
    assert isinstance(published, snapshot_module.BenchmarkSnapshot)
    assert isinstance(observed, snapshot_module.BenchmarkSnapshot)
    assert published.coverage_end_session == "2010-01-05"
    assert observed == published
    assert list(tmp_path.glob("*.rollback")) == []


def test_reader_discards_crash_recovery_link_after_durable_publication(
    tmp_path: Path,
) -> None:
    store = BenchmarkSnapshotStore(tmp_path)
    store.publish(
        (BenchmarkLevel("2010-01-04", "3592.47"),),
        published_at=PUBLISHED_AT,
    )
    recovery = tmp_path / f".{BENCHMARK_SNAPSHOT_FILENAME}.crash.rollback"
    snapshot_after_crash = BenchmarkSnapshotStore(tmp_path / "new")
    snapshot_after_crash.publish(
        (
            BenchmarkLevel("2010-01-04", "3592.47"),
            BenchmarkLevel("2010-01-05", "3545.19"),
        ),
        published_at=datetime(2026, 8, 28, tzinfo=UTC),
    )
    snapshot_module.os.link(store.path, recovery)
    snapshot_module.os.replace(snapshot_after_crash.path, store.path)

    recovered = store.read()

    assert recovered is not None
    assert recovered.coverage_end_session == "2010-01-05"
    assert not recovery.exists()


def test_reader_restores_only_recovery_link_when_target_is_missing(tmp_path: Path) -> None:
    store = BenchmarkSnapshotStore(tmp_path)
    original = store.publish(
        (BenchmarkLevel("2010-01-04", "3592.47"),),
        published_at=PUBLISHED_AT,
    )
    recovery = tmp_path / f".{BENCHMARK_SNAPSHOT_FILENAME}.crash.rollback"
    snapshot_module.os.replace(store.path, recovery)

    assert store.read() == original
    assert store.path.exists()
    assert not recovery.exists()


@pytest.mark.parametrize(
    ("replacement", "code"),
    [
        (
            (BenchmarkLevel("2010-01-04", "3592.47"),),
            "BENCHMARK_HISTORY_REGRESSION",
        ),
        (
            (
                BenchmarkLevel("2010-01-04", "3592.48"),
                BenchmarkLevel("2010-01-05", "3545.19"),
                BenchmarkLevel("2010-01-06", "3558.7"),
            ),
            "BENCHMARK_HISTORY_MUTATION",
        ),
    ],
)
def test_store_enforces_append_only_history(
    tmp_path: Path,
    replacement: tuple[BenchmarkLevel, ...],
    code: str,
) -> None:
    store = BenchmarkSnapshotStore(tmp_path)
    original = store.publish(
        (
            BenchmarkLevel("2010-01-04", "3592.47"),
            BenchmarkLevel("2010-01-05", "3545.19"),
        ),
        published_at=PUBLISHED_AT,
    )

    with pytest.raises(BenchmarkSnapshotError, match=code):
        store.publish(
            replacement,
            published_at=datetime(2026, 8, 28, tzinfo=UTC),
        )

    assert store.read() == original


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"unexpected": True}),
        lambda value: value["coverage"].update({"session_count": 99}),
        lambda value: value["levels"].append(value["levels"][0]),
        lambda value: value["levels"][0].update({"open_level": "Infinity"}),
    ],
)
def test_reader_rejects_non_strict_snapshot(
    tmp_path: Path,
    mutation: object,
) -> None:
    store = BenchmarkSnapshotStore(tmp_path)
    store.publish(
        (BenchmarkLevel("2010-01-04", "3592.47"),),
        published_at=PUBLISHED_AT,
    )
    path = tmp_path / BENCHMARK_SNAPSHOT_FILENAME
    value = json.loads(path.read_bytes())
    mutation(value)  # type: ignore[operator]
    path.write_text(json.dumps(value))

    with pytest.raises(BenchmarkSnapshotError):
        store.read()
