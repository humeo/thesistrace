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

MAX_WORKING_CACHE_BYTES = 8 * 1024 * 1024
_CACHE_SCHEMA_VERSION = 1
_CACHE_KEYS = {
    "checkpoint_bytes",
    "checkpoint_sha256",
    "checkpoint_zlib_base64",
    "compression",
    "fence",
    "head_manifest_sha256",
    "release_id",
    "schema_version",
    "track_id",
}


class _DailyTrackWorkingCache:
    """Latest verified continuation copy; never a source of product truth."""

    def __init__(self, root: Path, *, max_bytes: int = MAX_WORKING_CACHE_BYTES) -> None:
        if max_bytes <= 0:
            raise ValueError("Working Cache byte limit must be positive")
        self.root = root
        self.max_bytes = max_bytes
        self.root.mkdir(parents=True, exist_ok=False)

    def path(self, track_id: object) -> Path:
        digest = hashlib.sha256(str(track_id).encode()).hexdigest()
        return self.root / f"{digest}.json"

    def load(
        self,
        *,
        track_id: str,
        release_id: str,
        head_manifest_sha256: str,
        fence: int,
        verified_checkpoint: bytes,
    ) -> Mapping[str, object] | None:
        path = self.path(track_id)
        try:
            raw = path.read_bytes()
            if len(raw) > self.max_bytes:
                raise ValueError("Working Cache entry exceeds its byte limit")
            entry = json.loads(raw)
            if not isinstance(entry, dict) or set(entry) != _CACHE_KEYS:
                raise ValueError("Working Cache entry shape is invalid")
            expected = {
                "schema_version": _CACHE_SCHEMA_VERSION,
                "track_id": track_id,
                "release_id": release_id,
                "head_manifest_sha256": head_manifest_sha256,
                "fence": fence,
                "compression": "zlib",
                "checkpoint_bytes": len(verified_checkpoint),
                "checkpoint_sha256": hashlib.sha256(verified_checkpoint).hexdigest(),
            }
            if any(entry.get(key) != value for key, value in expected.items()):
                raise ValueError("Working Cache basis is stale")
            encoded = entry["checkpoint_zlib_base64"]
            if not isinstance(encoded, str):
                raise ValueError("Working Cache payload is invalid")
            compressed = base64.b64decode(encoded, validate=True)
            payload = _bounded_decompress(compressed, len(verified_checkpoint))
            if payload != verified_checkpoint:
                raise ValueError("Working Cache payload does not match verified truth")
            value = json.loads(payload)
            if not isinstance(value, Mapping):
                raise ValueError("Working Cache continuation state is invalid")
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
        release_id: str,
        head_manifest_sha256: str,
        fence: int,
        verified_checkpoint: bytes,
    ) -> bool:
        path = self.path(track_id)
        entry = {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "track_id": track_id,
            "release_id": release_id,
            "head_manifest_sha256": head_manifest_sha256,
            "fence": fence,
            "compression": "zlib",
            "checkpoint_bytes": len(verified_checkpoint),
            "checkpoint_sha256": hashlib.sha256(verified_checkpoint).hexdigest(),
            "checkpoint_zlib_base64": base64.b64encode(
                zlib.compress(verified_checkpoint, level=9)
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
