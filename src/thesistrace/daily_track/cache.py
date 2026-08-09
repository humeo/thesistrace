from __future__ import annotations

import base64
import hashlib
import json
import os
import zlib
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

from thesistrace.publication.serialization import canonical_json_bytes

MAX_WORKING_CACHE_BYTES = 2_097_152
MAX_PENDING_ALPHA_SESSIONS = 21
MAX_ROLLING_FACTOR_ROWS = 3 * 504
_CACHE_SCHEMA_VERSION = 1
_CACHE_KEYS = {
    "continuation_bytes",
    "continuation_sha256",
    "continuation_zlib_base64",
    "fence",
    "head_manifest_sha256",
    "pending_alpha_sessions",
    "basis_sha256",
    "rolling_factor_rows",
    "schema_version",
    "track_id",
}


class _DailyTrackWorkingCache:
    """Latest bounded continuation slices; never a source of product truth."""

    def __init__(self, root: Path, *, max_bytes: int = MAX_WORKING_CACHE_BYTES) -> None:
        if max_bytes <= 0:
            raise ValueError("Working Cache byte limit must be positive")
        self.root = root
        self.max_bytes = max_bytes
        self.root.mkdir(parents=True, exist_ok=False)

    def path(self, track_id: object) -> Path:
        digest = hashlib.sha256(str(track_id).encode()).hexdigest()
        return self.root / f"{digest}.json"

    def delete(self, track_id: str) -> None:
        _discard(self.path(track_id))

    def load(
        self,
        *,
        track_id: str,
        basis_sha256: str,
        head_manifest_sha256: str,
        fence: int,
        continuation_sha256: str,
        pending_alpha_sessions: int,
        rolling_factor_rows: int,
    ) -> Mapping[str, object] | None:
        path = self.path(track_id)
        try:
            with path.open("rb") as stream:
                raw = stream.read(self.max_bytes + 1)
            if len(raw) > self.max_bytes:
                raise ValueError("Working Cache entry exceeds its byte limit")
            entry = json.loads(raw)
            if not isinstance(entry, dict) or set(entry) != _CACHE_KEYS:
                raise ValueError("Working Cache entry shape is invalid")
            expected = {
                "schema_version": _CACHE_SCHEMA_VERSION,
                "track_id": track_id,
                "basis_sha256": basis_sha256,
                "head_manifest_sha256": head_manifest_sha256,
                "fence": fence,
                "continuation_sha256": continuation_sha256,
                "pending_alpha_sessions": pending_alpha_sessions,
                "rolling_factor_rows": rolling_factor_rows,
            }
            if any(entry.get(key) != value for key, value in expected.items()):
                raise ValueError("Working Cache basis is stale")
            continuation_bytes = entry.get("continuation_bytes")
            if (
                not isinstance(continuation_bytes, int)
                or continuation_bytes <= 0
                or continuation_bytes > self.max_bytes
            ):
                raise ValueError("Working Cache payload length is invalid")
            encoded = entry["continuation_zlib_base64"]
            if not isinstance(encoded, str):
                raise ValueError("Working Cache payload is invalid")
            compressed = base64.b64decode(encoded, validate=True)
            payload = _bounded_decompress(compressed, continuation_bytes)
            if hashlib.sha256(payload).hexdigest() != continuation_sha256:
                raise ValueError("Working Cache payload does not match verified truth")
            value = json.loads(payload)
            if not isinstance(value, Mapping):
                raise ValueError("Working Cache continuation state is invalid")
            if _continuation_counts(value) != (
                pending_alpha_sessions,
                rolling_factor_rows,
            ):
                raise ValueError("Working Cache continuation counts are invalid")
            return value
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError, zlib.error, json.JSONDecodeError):
            _discard(path)
            return None

    def store(
        self,
        *,
        track_id: str,
        basis_sha256: str,
        head_manifest_sha256: str,
        fence: int,
        verified_continuation: Mapping[str, object],
    ) -> bool:
        path = self.path(track_id)
        continuation = canonical_json_bytes(verified_continuation)
        pending_count, factor_count = _continuation_counts(verified_continuation)
        entry = {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "track_id": track_id,
            "basis_sha256": basis_sha256,
            "head_manifest_sha256": head_manifest_sha256,
            "fence": fence,
            "continuation_bytes": len(continuation),
            "continuation_sha256": hashlib.sha256(continuation).hexdigest(),
            "pending_alpha_sessions": pending_count,
            "rolling_factor_rows": factor_count,
            "continuation_zlib_base64": base64.b64encode(
                zlib.compress(continuation, level=9)
            ).decode("ascii"),
        }
        serialized = canonical_json_bytes(entry)
        if len(serialized) > self.max_bytes:
            _discard(path)
            return False
        temporary = self.root / f".{path.stem}-{uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except OSError:
            _discard(temporary)
            return False
        return True


def _continuation_counts(value: Mapping[str, object]) -> tuple[int, int]:
    if set(value) != {"schema_version", "pending_alpha", "rolling_factor"}:
        raise ValueError("Working Cache continuation shape is invalid")
    if value.get("schema_version") != "daily-track-working-state-v1":
        raise ValueError("Working Cache continuation version is invalid")
    pending = value.get("pending_alpha")
    rolling = value.get("rolling_factor")
    if not isinstance(pending, list) or len(pending) > MAX_PENDING_ALPHA_SESSIONS:
        raise ValueError("Working Cache Pending Alpha bound is invalid")
    if not isinstance(rolling, list) or len(rolling) > MAX_ROLLING_FACTOR_ROWS:
        raise ValueError("Working Cache rolling Factor bound is invalid")
    return len(pending), len(rolling)


def _bounded_decompress(compressed: bytes, expected_bytes: int) -> bytes:
    decompressor = zlib.decompressobj()
    payload = decompressor.decompress(compressed, expected_bytes + 1)
    if (
        len(payload) != expected_bytes
        or not decompressor.eof
        or decompressor.unconsumed_tail
        or decompressor.unused_data
    ):
        raise ValueError("Working Cache payload length is invalid")
    return payload


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
