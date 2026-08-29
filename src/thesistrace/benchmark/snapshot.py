from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import stat
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol

BENCHMARK_SNAPSHOT_FILENAME = "csi300-price-index-open.json"
BENCHMARK_SNAPSHOT_FORMAT = "thesistrace-benchmark-snapshot"
BENCHMARK_SNAPSHOT_VERSION = 1
BENCHMARK_CONTRACT_VERSION = "tushare-csi300-price-index-open-v1"
BENCHMARK_ID = "csi300-price-index-open"
BENCHMARK_DISPLAY_NAME = "沪深300"
BENCHMARK_TS_CODE = "399300.SZ"
BENCHMARK_KIND = "price_index"
BENCHMARK_COORDINATE = "open"
BENCHMARK_SOURCE_PROVIDER = "tushare"
BENCHMARK_SOURCE_API_NAME = "index_daily"
BENCHMARK_SOURCE_FIELD = "open"
BENCHMARK_SOURCE_FIELDS = ("ts_code", "trade_date", BENCHMARK_SOURCE_FIELD)
BENCHMARK_START_SESSION = "2010-01-04"
_SNAPSHOT_MAX_BYTES = 8 * 1024 * 1024
_SNAPSHOT_LOCK_FILENAME = f".{BENCHMARK_SNAPSHOT_FILENAME}.lock"


class BenchmarkSnapshotError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class BenchmarkLevel:
    session: str
    open_level: str


@dataclass(frozen=True)
class BenchmarkSnapshot:
    published_at: str
    coverage_start_session: str
    coverage_end_session: str
    levels: tuple[BenchmarkLevel, ...]
    sha256: str

    @property
    def level_by_session(self) -> dict[str, str]:
        return {level.session: level.open_level for level in self.levels}


@dataclass(frozen=True)
class BenchmarkSnapshotUpdate:
    snapshot: BenchmarkSnapshot
    published: bool


class BenchmarkLevelSource(Protocol):
    def collect_open_levels(
        self,
        *,
        start_session: str,
        end_session: str,
    ) -> Sequence[BenchmarkLevel]: ...


def validate_independent_benchmark_mount(
    data_mount: Path | str,
    benchmark_mount: Path | str,
) -> Path:
    data_root = Path(data_mount).resolve()
    benchmark_root = Path(benchmark_mount).resolve()
    if (
        data_root == benchmark_root
        or data_root.is_relative_to(benchmark_root)
        or benchmark_root.is_relative_to(data_root)
    ):
        raise ValueError("Benchmark mount must be independent of Canonical Data")
    return Path(benchmark_mount)


class BenchmarkSnapshotStore:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._path = self._root / BENCHMARK_SNAPSHOT_FILENAME

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> BenchmarkSnapshot | None:
        with self._exclusive_lock():
            return self._read_locked()

    def _read_locked(self) -> BenchmarkSnapshot | None:
        self._restore_missing_snapshot()
        try:
            descriptor = os.open(
                self._path,
                os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0),
            )
        except FileNotFoundError:
            return None
        except OSError as error:
            raise BenchmarkSnapshotError("BENCHMARK_SNAPSHOT_UNREADABLE") from error
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _SNAPSHOT_MAX_BYTES:
                raise BenchmarkSnapshotError("BENCHMARK_SNAPSHOT_INVALID_FILE")
            content = bytearray()
            while chunk := os.read(
                descriptor,
                min(64 * 1024, _SNAPSHOT_MAX_BYTES + 1 - len(content)),
            ):
                content.extend(chunk)
                if len(content) > _SNAPSHOT_MAX_BYTES:
                    raise BenchmarkSnapshotError("BENCHMARK_SNAPSHOT_TOO_LARGE")
            if len(content) != metadata.st_size:
                raise BenchmarkSnapshotError("BENCHMARK_SNAPSHOT_CHANGED_DURING_READ")
        finally:
            os.close(descriptor)
        snapshot = _decode_snapshot(bytes(content))
        self._discard_recovery_links()
        return snapshot

    def publish(
        self,
        levels: Sequence[BenchmarkLevel],
        *,
        published_at: datetime,
    ) -> BenchmarkSnapshot:
        if published_at.tzinfo is None:
            raise BenchmarkSnapshotError("BENCHMARK_PUBLICATION_TIME_INVALID")
        normalized_levels = _validate_levels(tuple(levels))
        with self._exclusive_lock():
            current = self._read_locked()
            if current is not None:
                _require_append_only_publication(current.levels, normalized_levels)
            timestamp = published_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
            payload = {
                "format": BENCHMARK_SNAPSHOT_FORMAT,
                "version": BENCHMARK_SNAPSHOT_VERSION,
                "contract_version": BENCHMARK_CONTRACT_VERSION,
                "benchmark": {
                    "id": BENCHMARK_ID,
                    "display_name": BENCHMARK_DISPLAY_NAME,
                    "ts_code": BENCHMARK_TS_CODE,
                    "kind": BENCHMARK_KIND,
                    "coordinate": BENCHMARK_COORDINATE,
                },
                "source": {
                    "provider": BENCHMARK_SOURCE_PROVIDER,
                    "api_name": BENCHMARK_SOURCE_API_NAME,
                    "field": BENCHMARK_SOURCE_FIELD,
                },
                "published_at": timestamp,
                "coverage": {
                    "start_session": normalized_levels[0].session,
                    "end_session": normalized_levels[-1].session,
                    "session_count": len(normalized_levels),
                },
                "levels": [
                    {"session": level.session, "open_level": level.open_level}
                    for level in normalized_levels
                ],
            }
            content = _canonical_json_bytes(payload)
            if len(content) > _SNAPSHOT_MAX_BYTES:
                raise BenchmarkSnapshotError("BENCHMARK_SNAPSHOT_TOO_LARGE")
            snapshot = _decode_snapshot(content)
            self._atomic_replace(content)
            return snapshot

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        self._root.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self._root / _SNAPSHOT_LOCK_FILENAME,
            os.O_CREAT
            | os.O_RDWR
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise BenchmarkSnapshotError("BENCHMARK_LOCK_INVALID_FILE")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    def _atomic_replace(self, content: bytes) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self._root,
            prefix=f".{BENCHMARK_SNAPSHOT_FILENAME}.",
            suffix=".tmp",
        )
        temporary: Path | None = Path(temporary_name)
        rollback: Path | None = None
        committed = False
        try:
            view = memoryview(content)
            written = 0
            while written < len(view):
                written += os.write(descriptor, view[written:])
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            if self._path.exists():
                rollback = self._root / (
                    f".{BENCHMARK_SNAPSHOT_FILENAME}.{secrets.token_hex(16)}.rollback"
                )
                os.link(self._path, rollback, follow_symlinks=False)
            self._sync_directory()
            assert temporary is not None
            os.replace(temporary, self._path)
            temporary = None
            committed = True
            try:
                self._sync_directory()
            except Exception as publication_error:
                try:
                    self._rollback_replace(rollback)
                    rollback = None
                except Exception as rollback_error:
                    raise BenchmarkSnapshotError(
                        "BENCHMARK_PUBLICATION_ROLLBACK_FAILED"
                    ) from rollback_error
                raise publication_error
        except Exception:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            if not committed and rollback is not None:
                rollback.unlink(missing_ok=True)
            raise
        if rollback is not None:
            try:
                rollback.unlink()
            except OSError as cleanup_error:
                try:
                    self._rollback_replace(rollback)
                except Exception as rollback_error:
                    raise BenchmarkSnapshotError(
                        "BENCHMARK_PUBLICATION_ROLLBACK_FAILED"
                    ) from rollback_error
                raise cleanup_error
            try:
                self._sync_directory()
            except OSError:
                # The new Snapshot and the visible removal are already committed in
                # process. If a crash resurrects the link, read() reconciles it.
                pass

    def _rollback_replace(self, rollback: Path | None) -> None:
        if rollback is None:
            self._path.unlink(missing_ok=True)
        else:
            os.replace(rollback, self._path)
        self._sync_directory()

    def _sync_directory(self) -> None:
        directory = os.open(self._root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def _restore_missing_snapshot(self) -> None:
        recovery_links = self._recovery_links()
        if self._path.exists() or not recovery_links:
            return
        if len(recovery_links) != 1:
            raise BenchmarkSnapshotError("BENCHMARK_RECOVERY_AMBIGUOUS")
        os.replace(recovery_links[0], self._path)
        self._sync_directory()

    def _discard_recovery_links(self) -> None:
        recovery_links = self._recovery_links()
        if not recovery_links:
            return
        try:
            for recovery in recovery_links:
                recovery.unlink()
            self._sync_directory()
        except OSError as error:
            raise BenchmarkSnapshotError("BENCHMARK_RECOVERY_CLEANUP_FAILED") from error

    def _recovery_links(self) -> tuple[Path, ...]:
        if not self._root.exists():
            return ()
        return tuple(
            sorted(
                self._root.glob(f".{BENCHMARK_SNAPSHOT_FILENAME}.*.rollback"),
                key=os.fspath,
            )
        )


class BenchmarkSnapshotUpdater:
    def __init__(
        self,
        store: BenchmarkSnapshotStore,
        source: BenchmarkLevelSource,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._source = source
        self._clock = clock

    def update(
        self,
        required_sessions: Sequence[str],
        *,
        published_at: datetime | None = None,
    ) -> BenchmarkSnapshotUpdate:
        sessions = _validate_required_sessions(tuple(required_sessions))
        current = self._store.read()
        if current is not None:
            _require_existing_prefix_complete(current, sessions)
            if current.coverage_end_session >= sessions[-1]:
                return BenchmarkSnapshotUpdate(snapshot=current, published=False)
            start_session = (
                date.fromisoformat(current.coverage_end_session) + timedelta(days=1)
            ).isoformat()
        else:
            start_session = BENCHMARK_START_SESSION
        collected = tuple(
            self._source.collect_open_levels(
                start_session=start_session,
                end_session=sessions[-1],
            )
        )
        appended = _validate_collected_levels(
            collected,
            start_session=start_session,
            end_session=sessions[-1],
        )
        combined = (*(() if current is None else current.levels), *appended)
        _require_level_sessions(combined, sessions)
        selected_publication_time = self._clock() if published_at is None else published_at
        if not isinstance(selected_publication_time, datetime):
            raise BenchmarkSnapshotError("BENCHMARK_PUBLICATION_TIME_INVALID")
        snapshot = self._store.publish(combined, published_at=selected_publication_time)
        return BenchmarkSnapshotUpdate(snapshot=snapshot, published=True)


def _decode_snapshot(content: bytes) -> BenchmarkSnapshot:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BenchmarkSnapshotError("BENCHMARK_SNAPSHOT_INVALID_JSON") from error
    if not isinstance(value, dict) or set(value) != {
        "format",
        "version",
        "contract_version",
        "benchmark",
        "source",
        "published_at",
        "coverage",
        "levels",
    }:
        raise BenchmarkSnapshotError("BENCHMARK_SNAPSHOT_INVALID_CONTRACT")
    if (
        value["format"] != BENCHMARK_SNAPSHOT_FORMAT
        or value["version"] != BENCHMARK_SNAPSHOT_VERSION
        or isinstance(value["version"], bool)
        or value["contract_version"] != BENCHMARK_CONTRACT_VERSION
    ):
        raise BenchmarkSnapshotError("BENCHMARK_SNAPSHOT_INCOMPATIBLE")
    _validate_exact_mapping(
        value["benchmark"],
        {
            "id": BENCHMARK_ID,
            "display_name": BENCHMARK_DISPLAY_NAME,
            "ts_code": BENCHMARK_TS_CODE,
            "kind": BENCHMARK_KIND,
            "coordinate": BENCHMARK_COORDINATE,
        },
        "BENCHMARK_IDENTITY_INVALID",
    )
    _validate_exact_mapping(
        value["source"],
        {
            "provider": BENCHMARK_SOURCE_PROVIDER,
            "api_name": BENCHMARK_SOURCE_API_NAME,
            "field": BENCHMARK_SOURCE_FIELD,
        },
        "BENCHMARK_SOURCE_IDENTITY_INVALID",
    )
    published_at = _published_at(value["published_at"])
    raw_levels = value["levels"]
    if not isinstance(raw_levels, list):
        raise BenchmarkSnapshotError("BENCHMARK_LEVELS_INVALID")
    levels: list[BenchmarkLevel] = []
    for raw in raw_levels:
        if not isinstance(raw, dict) or set(raw) != {"session", "open_level"}:
            raise BenchmarkSnapshotError("BENCHMARK_LEVEL_INVALID")
        levels.append(BenchmarkLevel(session=raw["session"], open_level=raw["open_level"]))
    normalized = _validate_levels(tuple(levels))
    coverage = value["coverage"]
    if not isinstance(coverage, dict) or set(coverage) != {
        "start_session",
        "end_session",
        "session_count",
    }:
        raise BenchmarkSnapshotError("BENCHMARK_COVERAGE_INVALID")
    if (
        coverage["start_session"] != normalized[0].session
        or coverage["end_session"] != normalized[-1].session
        or coverage["session_count"] != len(normalized)
        or isinstance(coverage["session_count"], bool)
    ):
        raise BenchmarkSnapshotError("BENCHMARK_COVERAGE_INVALID")
    return BenchmarkSnapshot(
        published_at=published_at,
        coverage_start_session=normalized[0].session,
        coverage_end_session=normalized[-1].session,
        levels=normalized,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _validate_levels(levels: tuple[BenchmarkLevel, ...]) -> tuple[BenchmarkLevel, ...]:
    if not levels or levels[0].session != BENCHMARK_START_SESSION:
        raise BenchmarkSnapshotError("BENCHMARK_COVERAGE_START_INVALID")
    prior: str | None = None
    normalized: list[BenchmarkLevel] = []
    for level in levels:
        if not isinstance(level.session, str) or _iso_date(level.session) != level.session:
            raise BenchmarkSnapshotError("BENCHMARK_SESSION_INVALID")
        if prior is not None and level.session <= prior:
            raise BenchmarkSnapshotError("BENCHMARK_SESSIONS_NOT_STRICTLY_ORDERED")
        if not isinstance(level.open_level, str):
            raise BenchmarkSnapshotError("BENCHMARK_LEVEL_INVALID")
        canonical = _decimal_string(level.open_level)
        if canonical != level.open_level:
            raise BenchmarkSnapshotError("BENCHMARK_LEVEL_NOT_CANONICAL")
        normalized.append(level)
        prior = level.session
    return tuple(normalized)


def _validate_collected_levels(
    levels: tuple[BenchmarkLevel, ...],
    *,
    start_session: str,
    end_session: str,
) -> tuple[BenchmarkLevel, ...]:
    if not levels:
        raise BenchmarkSnapshotError("BENCHMARK_COVERAGE_INSUFFICIENT")
    prior: str | None = None
    normalized: list[BenchmarkLevel] = []
    for level in levels:
        if not isinstance(level, BenchmarkLevel):
            raise BenchmarkSnapshotError("BENCHMARK_LEVEL_INVALID")
        if _iso_date(level.session) != level.session:
            raise BenchmarkSnapshotError("BENCHMARK_SESSION_INVALID")
        if level.session < start_session or level.session > end_session:
            raise BenchmarkSnapshotError("BENCHMARK_SOURCE_WINDOW_INVALID")
        if prior is not None and level.session <= prior:
            raise BenchmarkSnapshotError("BENCHMARK_SESSIONS_NOT_STRICTLY_ORDERED")
        canonical = _decimal_string(level.open_level)
        normalized.append(BenchmarkLevel(level.session, canonical))
        prior = level.session
    if start_session == BENCHMARK_START_SESSION and normalized[0].session != start_session:
        raise BenchmarkSnapshotError("BENCHMARK_COVERAGE_START_INVALID")
    return tuple(normalized)


def _validate_required_sessions(sessions: tuple[str, ...]) -> tuple[str, ...]:
    if not sessions or sessions != tuple(sorted(set(sessions))):
        raise BenchmarkSnapshotError("BENCHMARK_REQUIRED_SESSIONS_INVALID")
    for session in sessions:
        if _iso_date(session) != session:
            raise BenchmarkSnapshotError("BENCHMARK_REQUIRED_SESSIONS_INVALID")
    benchmark_sessions = tuple(
        session for session in sessions if session >= BENCHMARK_START_SESSION
    )
    if not benchmark_sessions:
        raise BenchmarkSnapshotError("BENCHMARK_REQUIRED_SESSIONS_INVALID")
    return benchmark_sessions


def _require_existing_prefix_complete(
    snapshot: BenchmarkSnapshot,
    sessions: Sequence[str],
) -> None:
    covered_sessions = [session for session in sessions if session <= snapshot.coverage_end_session]
    _require_level_sessions(snapshot.levels, covered_sessions)


def _require_append_only_publication(
    current: Sequence[BenchmarkLevel],
    replacement: Sequence[BenchmarkLevel],
) -> None:
    if len(replacement) < len(current):
        raise BenchmarkSnapshotError("BENCHMARK_HISTORY_REGRESSION")
    if tuple(replacement[: len(current)]) != tuple(current):
        raise BenchmarkSnapshotError("BENCHMARK_HISTORY_MUTATION")


def _require_level_sessions(
    levels: Sequence[BenchmarkLevel],
    required_sessions: Sequence[str],
) -> None:
    available = {level.session for level in levels}
    if any(session not in available for session in required_sessions):
        raise BenchmarkSnapshotError("BENCHMARK_COVERAGE_INSUFFICIENT")


def _validate_exact_mapping(value: object, expected: Mapping[str, object], code: str) -> None:
    if not isinstance(value, dict) or value != expected:
        raise BenchmarkSnapshotError(code)


def _published_at(value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise BenchmarkSnapshotError("BENCHMARK_PUBLICATION_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise BenchmarkSnapshotError("BENCHMARK_PUBLICATION_TIME_INVALID") from error
    canonical = parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if parsed.utcoffset() != timedelta(0) or canonical != value:
        raise BenchmarkSnapshotError("BENCHMARK_PUBLICATION_TIME_INVALID")
    return value


def _iso_date(value: object) -> str:
    if not isinstance(value, str):
        raise BenchmarkSnapshotError("BENCHMARK_SESSION_INVALID")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise BenchmarkSnapshotError("BENCHMARK_SESSION_INVALID") from error


def _decimal_string(value: object) -> str:
    if not isinstance(value, (str, int, float, Decimal)) or isinstance(value, bool):
        raise BenchmarkSnapshotError("BENCHMARK_LEVEL_INVALID")
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise BenchmarkSnapshotError("BENCHMARK_LEVEL_INVALID") from error
    if not decimal.is_finite() or decimal <= 0:
        raise BenchmarkSnapshotError("BENCHMARK_LEVEL_INVALID")
    canonical = format(decimal, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    return canonical


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


__all__ = (
    "BENCHMARK_CONTRACT_VERSION",
    "BENCHMARK_COORDINATE",
    "BENCHMARK_DISPLAY_NAME",
    "BENCHMARK_ID",
    "BENCHMARK_KIND",
    "BENCHMARK_SNAPSHOT_FILENAME",
    "BENCHMARK_SOURCE_API_NAME",
    "BENCHMARK_SOURCE_FIELD",
    "BENCHMARK_SOURCE_FIELDS",
    "BENCHMARK_SOURCE_PROVIDER",
    "BENCHMARK_START_SESSION",
    "BENCHMARK_TS_CODE",
    "BenchmarkLevel",
    "BenchmarkLevelSource",
    "BenchmarkSnapshot",
    "BenchmarkSnapshotError",
    "BenchmarkSnapshotStore",
    "BenchmarkSnapshotUpdate",
    "BenchmarkSnapshotUpdater",
    "validate_independent_benchmark_mount",
)
