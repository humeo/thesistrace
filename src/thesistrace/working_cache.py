import fcntl
import hashlib
import json
import os
import shutil
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

from thesistrace.objects import (
    ParquetContractError,
    ParquetWriterContract,
    canonical_json_bytes,
    parquet_bytes,
)

MAX_CACHE_BYTES = 2_097_152
MAX_PENDING_ALPHA_SESSIONS = 21
MAX_ROLLING_FACTOR_ROWS = 1_512
SHARED_DIRECTORY_MODE = 0o2770
SHARED_FILE_MODE = 0o660

PENDING_ALPHA_CONTRACT = ParquetWriterContract(
    name="working-cache.pending-alpha",
    version=1,
    schema=pa.schema(
        [
            pa.field("instrument_id", pa.string(), nullable=False),
            pa.field("alpha", pa.float64(), nullable=False),
        ]
    ),
    sort_keys=("instrument_id",),
)

ROLLING_FACTOR_CONTRACT = ParquetWriterContract(
    name="working-cache.rolling-factor",
    version=1,
    schema=pa.schema(
        [
            pa.field("session", pa.string(), nullable=False),
            pa.field("horizon", pa.int16(), nullable=False),
            pa.field("sample_count", pa.int32(), nullable=False),
            pa.field("ic", pa.float64(), nullable=True),
            pa.field("rank_ic", pa.float64(), nullable=True),
            pa.field("q1", pa.float64(), nullable=True),
            pa.field("q2", pa.float64(), nullable=True),
            pa.field("q3", pa.float64(), nullable=True),
            pa.field("q4", pa.float64(), nullable=True),
            pa.field("q5", pa.float64(), nullable=True),
            pa.field("top_bottom_return", pa.float64(), nullable=True),
            pa.field("correlation_reason", pa.string(), nullable=True),
            pa.field("quantile_reason", pa.string(), nullable=True),
        ]
    ),
    sort_keys=("session", "horizon"),
)


class WorkingCacheError(RuntimeError):
    pass


class WorkingCacheStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def commit_seed(
        self,
        coordinates: Mapping[str, object],
        *,
        pending_alpha: Mapping[str, Sequence[Mapping[str, object]]],
        rolling_factor: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        track_id = required_coordinate(coordinates, "daily_track_id")
        if len(pending_alpha) > MAX_PENDING_ALPHA_SESSIONS:
            raise WorkingCacheError("pending Alpha exceeds 21 sessions")
        if len(rolling_factor) > MAX_ROLLING_FACTOR_ROWS:
            raise WorkingCacheError("rolling Factor exceeds 1,512 rows")

        destination = self._track_path(track_id)
        if destination.exists():
            raise WorkingCacheError(f"Working Cache already exists for {track_id}")
        staging = self.root / ".staging" / f"{track_id}-{uuid4().hex}"
        ensure_shared_directory(staging.parent)
        ensure_shared_directory(staging, exist_ok=False)
        try:
            pending_entries: list[dict[str, object]] = []
            for session, rows in sorted(pending_alpha.items()):
                entry = self._write_parquet(
                    staging,
                    f"pending/{session}",
                    rows,
                    PENDING_ALPHA_CONTRACT,
                )
                pending_entries.append({"session": session, **entry})
            rolling_entry = self._write_parquet(
                staging,
                "rolling-factor",
                rolling_factor,
                ROLLING_FACTOR_CONTRACT,
            )
            basis = {
                key: coordinates[key]
                for key in (
                    "daily_track_id",
                    "generation_id",
                    "basis_checkpoint_id",
                    "basis_checkpoint_sha256",
                    "definition_content_hash",
                    "calculation_kernel",
                    "numeric_execution_contract",
                    "basis_dataset_release_id",
                    "fencing_token",
                )
            }
            basis["pending_alpha"] = pending_entries
            basis["rolling_factor"] = rolling_entry
            basis["payload_bytes"] = sum(
                int(entry["bytes"]) for entry in pending_entries
            ) + int(rolling_entry["bytes"])
            basis_payload = canonical_json_bytes(basis)
            write_shared_bytes(staging / "basis.json", basis_payload)
            total_bytes = sum(
                path.stat().st_size for path in staging.rglob("*") if path.is_file()
            )
            if total_bytes > MAX_CACHE_BYTES:
                raise WorkingCacheError(
                    f"Working Cache seed is {total_bytes} bytes; limit is {MAX_CACHE_BYTES}"
                )
            ensure_shared_directory(destination.parent)
            with self._track_lock(track_id):
                fence = self._read_fence(track_id)
                if fence is not None and fence["stopped"]:
                    raise WorkingCacheError(
                        "stopped DailyTrack cannot recreate a Working Cache"
                    )
                os.replace(staging, destination)
            remove_empty_directory(self.root / ".staging")
            return basis
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            remove_empty_directory(self.root / ".staging")
            raise

    def read_basis(self, track_id: str) -> dict[str, object]:
        value = json.loads((self._track_path(track_id) / "basis.json").read_text())
        if not isinstance(value, dict):
            raise WorkingCacheError("Working Cache basis is invalid")
        return value

    def validate(
        self,
        track_id: str,
        expected_coordinates: Mapping[str, object],
    ) -> dict[str, object]:
        basis = self.read_basis(track_id)
        for key, expected in expected_coordinates.items():
            if basis.get(key) != expected:
                raise WorkingCacheError(f"Working Cache basis mismatch: {key}")
        pending = basis.get("pending_alpha")
        rolling = basis.get("rolling_factor")
        if not isinstance(pending, list) or len(pending) > MAX_PENDING_ALPHA_SESSIONS:
            raise WorkingCacheError("Working Cache pending Alpha bound is invalid")
        if not isinstance(rolling, dict):
            raise WorkingCacheError("Working Cache rolling Factor index is invalid")
        if int(rolling.get("rows", -1)) > MAX_ROLLING_FACTOR_ROWS:
            raise WorkingCacheError("Working Cache rolling Factor bound is invalid")
        if self.namespace_bytes(track_id) > MAX_CACHE_BYTES:
            raise WorkingCacheError("Working Cache namespace exceeds its byte limit")
        self.read_pending_alpha(track_id)
        rolling_rows = self.read_rolling_factor(track_id)
        if len(rolling_rows) != int(rolling["rows"]):
            raise WorkingCacheError("Working Cache rolling Factor row count is invalid")
        referenced = {
            "basis.json",
            *(str(entry["path"]) for entry in pending if isinstance(entry, dict)),
            str(rolling["path"]),
        }
        actual = {
            path.relative_to(self._track_path(track_id)).as_posix()
            for path in self._track_path(track_id).rglob("*")
            if path.is_file()
        }
        if actual != referenced:
            raise WorkingCacheError("Working Cache namespace contains partial payloads")
        return basis

    def commit_advance(
        self,
        coordinates: Mapping[str, object],
        *,
        retained_pending_sessions: Sequence[str],
        new_pending_alpha: Mapping[str, Sequence[Mapping[str, object]]],
        rolling_factor: Sequence[Mapping[str, object]],
        attempt_id: str = "inline",
        before_install: Callable[[], None] | None = None,
    ) -> dict[str, object]:
        track_id = required_coordinate(coordinates, "daily_track_id")
        current_basis = self.read_basis(track_id)
        incoming_token = int(coordinates["fencing_token"])
        if incoming_token <= int(current_basis["fencing_token"]):
            raise WorkingCacheError("Working Cache commit has a stale fencing token")
        current_entries = current_basis.get("pending_alpha")
        if not isinstance(current_entries, list):
            raise WorkingCacheError("pending Alpha index is invalid")
        retained = set(retained_pending_sessions)
        if len(retained) + len(new_pending_alpha) > MAX_PENDING_ALPHA_SESSIONS:
            raise WorkingCacheError("pending Alpha exceeds 21 sessions")
        if len(rolling_factor) > MAX_ROLLING_FACTOR_ROWS:
            raise WorkingCacheError("rolling Factor exceeds 1,512 rows")
        indexed = {
            str(entry["session"]): entry
            for entry in current_entries
            if isinstance(entry, dict)
        }
        if not retained <= set(indexed):
            raise WorkingCacheError("retained Pending Alpha is missing from current cache")

        destination = self._track_path(track_id)
        staging = (
            self.root
            / ".staging"
            / f"{track_id}-{path_safe_attempt(attempt_id)}-{uuid4().hex}"
        )
        backup = (
            self.root
            / ".staging"
            / f"{track_id}-{path_safe_attempt(attempt_id)}-old-{uuid4().hex}"
        )
        ensure_shared_directory(staging.parent)
        ensure_shared_directory(staging, exist_ok=False)
        replaced = False
        try:
            pending_entries: list[dict[str, object]] = []
            for session in sorted(retained):
                entry = dict(indexed[session])
                source = destination / str(entry["path"])
                target = staging / str(entry["path"])
                ensure_shared_directory(target.parent)
                os.link(source, target)
                pending_entries.append(entry)
            for session, rows in sorted(new_pending_alpha.items()):
                if session in retained:
                    raise WorkingCacheError("new Pending Alpha duplicates a retained session")
                entry = self._write_parquet(
                    staging,
                    f"pending/{session}",
                    rows,
                    PENDING_ALPHA_CONTRACT,
                )
                pending_entries.append({"session": session, **entry})
            pending_entries.sort(key=lambda entry: str(entry["session"]))
            rolling_entry = self._write_parquet(
                staging,
                "rolling-factor",
                rolling_factor,
                ROLLING_FACTOR_CONTRACT,
            )
            basis = self._basis(
                coordinates,
                pending_entries,
                rolling_entry,
            )
            write_shared_bytes(staging / "basis.json", canonical_json_bytes(basis))
            total_bytes = directory_bytes(staging)
            if total_bytes > MAX_CACHE_BYTES:
                raise WorkingCacheError(
                    f"Working Cache advance is {total_bytes} bytes; limit is {MAX_CACHE_BYTES}"
                )
            if before_install is not None:
                before_install()
            with self._track_lock(track_id):
                fence = self._read_fence(track_id)
                if (
                    fence is None
                    or fence["stopped"]
                    or int(fence["fencing_token"]) != incoming_token
                ):
                    raise WorkingCacheError(
                        "Working Cache commit has a stale fencing token"
                    )
                installed_basis = self.read_basis(track_id)
                if incoming_token <= int(installed_basis["fencing_token"]):
                    raise WorkingCacheError(
                        "Working Cache commit has a stale fencing token"
                    )
                os.replace(destination, backup)
                replaced = True
                try:
                    os.replace(staging, destination)
                except Exception:
                    os.replace(backup, destination)
                    replaced = False
                    raise
            shutil.rmtree(backup, ignore_errors=True)
            replaced = False
            remove_empty_directory(self.root / ".staging")
            return basis
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            if replaced and backup.exists() and not destination.exists():
                os.replace(backup, destination)
            shutil.rmtree(backup, ignore_errors=True)
            remove_empty_directory(self.root / ".staging")
            raise

    def read_pending_alpha(
        self,
        track_id: str,
    ) -> dict[str, list[dict[str, object]]]:
        basis = self.read_basis(track_id)
        entries = basis.get("pending_alpha")
        if not isinstance(entries, list):
            raise WorkingCacheError("pending Alpha index is invalid")
        result: dict[str, list[dict[str, object]]] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise WorkingCacheError("pending Alpha entry is invalid")
            result[str(entry["session"])] = self._read_parquet(
                track_id,
                entry,
                PENDING_ALPHA_CONTRACT,
            )
        return result

    def read_rolling_factor(self, track_id: str) -> list[dict[str, object]]:
        basis = self.read_basis(track_id)
        entry = basis.get("rolling_factor")
        if not isinstance(entry, dict):
            raise WorkingCacheError("rolling Factor index is invalid")
        return self._read_parquet(track_id, entry, ROLLING_FACTOR_CONTRACT)

    def namespace_bytes(self, track_id: str) -> int:
        path = self._track_path(track_id)
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())

    def list_track_ids(self) -> list[str]:
        tracks = self.root / "tracks"
        if not tracks.exists():
            return []
        return sorted(path.name for path in tracks.iterdir() if path.is_dir())

    def delete(self, track_id: str) -> None:
        shutil.rmtree(self._track_path(track_id), ignore_errors=True)

    def delete_if_not_newer(self, track_id: str, fencing_token: int) -> None:
        with self._track_lock(track_id):
            fence = self._read_fence(track_id)
            if fence is not None and int(fence["fencing_token"]) > fencing_token:
                raise WorkingCacheError(
                    "stale fencing token cannot delete the current Working Cache"
                )
            path = self._track_path(track_id)
            if not path.exists():
                return
            try:
                basis = self.read_basis(track_id)
            except (OSError, ValueError):
                shutil.rmtree(path)
                return
            if int(basis["fencing_token"]) > fencing_token:
                raise WorkingCacheError(
                    "stale fencing token cannot delete the current Working Cache"
                )
            shutil.rmtree(path)

    def discard_staging(self) -> None:
        shutil.rmtree(self.root / ".staging", ignore_errors=True)

    def advance_fence(
        self,
        track_id: str,
        fencing_token: int,
        *,
        stopped: bool,
    ) -> dict[str, object]:
        with self._track_lock(track_id):
            current = self._read_fence(track_id)
            if current is not None and int(current["fencing_token"]) > fencing_token:
                raise WorkingCacheError("Working Cache fence cannot move backwards")
            if current is not None and current["stopped"] and not stopped:
                raise WorkingCacheError("stopped DailyTrack fence is permanent")
            value = {
                "daily_track_id": track_id,
                "fencing_token": fencing_token,
                "stopped": stopped or bool(current and current["stopped"]),
            }
            destination = self._fence_path(track_id)
            ensure_shared_directory(destination.parent)
            temporary = destination.with_name(
                f".{destination.name}.{uuid4().hex}.tmp"
            )
            write_shared_bytes(temporary, canonical_json_bytes(value))
            os.replace(temporary, destination)
            return value

    def read_fence(self, track_id: str) -> dict[str, object] | None:
        with self._track_lock(track_id):
            return self._read_fence(track_id)

    def _track_path(self, track_id: str) -> Path:
        if not track_id or "/" in track_id or track_id in {".", ".."}:
            raise WorkingCacheError("DailyTrack id is not path-safe")
        return self.root / "tracks" / track_id

    def _fence_path(self, track_id: str) -> Path:
        self._track_path(track_id)
        return self.root / "fences" / f"{track_id}.json"

    def _read_fence(self, track_id: str) -> dict[str, object] | None:
        path = self._fence_path(track_id)
        if not path.exists():
            return None
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise WorkingCacheError("Working Cache fence is invalid")
        return value

    @contextmanager
    def _track_lock(self, track_id: str) -> Iterator[None]:
        self._track_path(track_id)
        path = self.root / "locks" / f"{track_id}.lock"
        ensure_shared_directory(path.parent)
        if not path.exists():
            try:
                descriptor = os.open(
                    path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    SHARED_FILE_MODE,
                )
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
                path.chmod(SHARED_FILE_MODE)
        with path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _basis(
        coordinates: Mapping[str, object],
        pending_entries: Sequence[Mapping[str, object]],
        rolling_entry: Mapping[str, object],
    ) -> dict[str, object]:
        basis = {
            key: coordinates[key]
            for key in (
                "daily_track_id",
                "generation_id",
                "basis_checkpoint_id",
                "basis_checkpoint_sha256",
                "definition_content_hash",
                "calculation_kernel",
                "numeric_execution_contract",
                "basis_dataset_release_id",
                "fencing_token",
            )
        }
        basis["pending_alpha"] = [dict(entry) for entry in pending_entries]
        basis["rolling_factor"] = dict(rolling_entry)
        basis["payload_bytes"] = sum(
            int(entry["bytes"]) for entry in pending_entries
        ) + int(rolling_entry["bytes"])
        return basis

    @staticmethod
    def _write_parquet(
        staging: Path,
        stem: str,
        rows: Sequence[Mapping[str, object]],
        contract: ParquetWriterContract,
    ) -> dict[str, object]:
        payload = parquet_bytes(rows, contract)
        digest = hashlib.sha256(payload).hexdigest()
        relative = Path(f"{stem}-{digest}.parquet")
        destination = staging / relative
        ensure_shared_directory(destination.parent)
        write_shared_bytes(destination, payload)
        return {
            "path": relative.as_posix(),
            "sha256": digest,
            "bytes": len(payload),
            "rows": len(rows),
            "writer_contract_id": contract.identifier,
        }

    def _read_parquet(
        self,
        track_id: str,
        entry: Mapping[str, object],
        contract: ParquetWriterContract,
    ) -> list[dict[str, object]]:
        if entry.get("writer_contract_id") != contract.identifier:
            raise WorkingCacheError("Working Cache writer contract is unsupported")
        path = self._track_path(track_id) / str(entry["path"])
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != entry.get("sha256") or len(payload) != entry.get("bytes"):
            raise WorkingCacheError("Working Cache payload checksum does not match")
        table = pq.read_table(pa.BufferReader(payload))
        if not table.schema.equals(contract.schema, check_metadata=True):
            raise ParquetContractError("Working Cache payload schema does not match")
        return table.to_pylist()


def required_coordinate(coordinates: Mapping[str, object], key: str) -> str:
    value = coordinates.get(key)
    if not isinstance(value, str) or not value:
        raise WorkingCacheError(f"Working Cache coordinate is missing {key}")
    return value


def path_safe_attempt(attempt_id: str) -> str:
    if not attempt_id or "/" in attempt_id or attempt_id in {".", ".."}:
        raise WorkingCacheError("Attempt id is not path-safe")
    return attempt_id


def directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def remove_empty_directory(path: Path) -> None:
    try:
        path.rmdir()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def ensure_shared_directory(path: Path, *, exist_ok: bool = True) -> None:
    if path.exists():
        if not exist_ok or not path.is_dir():
            raise FileExistsError(path)
        return
    try:
        path.mkdir(
            mode=SHARED_DIRECTORY_MODE,
            parents=True,
            exist_ok=False,
        )
    except FileExistsError:
        if not exist_ok or not path.is_dir():
            raise
        return
    path.chmod(SHARED_DIRECTORY_MODE)


def write_shared_bytes(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(SHARED_FILE_MODE)
