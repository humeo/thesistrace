import hashlib
import json
import os
import shutil
from collections.abc import Mapping, Sequence
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
        staging.mkdir(parents=True, exist_ok=False)
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
            (staging / "basis.json").write_bytes(basis_payload)
            total_bytes = sum(
                path.stat().st_size for path in staging.rglob("*") if path.is_file()
            )
            if total_bytes > MAX_CACHE_BYTES:
                raise WorkingCacheError(
                    f"Working Cache seed is {total_bytes} bytes; limit is {MAX_CACHE_BYTES}"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, destination)
            return basis
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def read_basis(self, track_id: str) -> dict[str, object]:
        value = json.loads((self._track_path(track_id) / "basis.json").read_text())
        if not isinstance(value, dict):
            raise WorkingCacheError("Working Cache basis is invalid")
        return value

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

    def _track_path(self, track_id: str) -> Path:
        if not track_id or "/" in track_id or track_id in {".", ".."}:
            raise WorkingCacheError("DailyTrack id is not path-safe")
        return self.root / "tracks" / track_id

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
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
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
