from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path

from thesistrace.daily_track.cache import (
    MAX_WORKING_CACHE_BYTES,
    _DailyTrackWorkingCache,
)
from thesistrace.publication.serialization import canonical_json_bytes

TRACK_ID = "working-cache-contract"
BASIS_SHA256 = "basis-a"
HEAD_MANIFEST_SHA256 = "checkpoint-a"
FENCE = 7
CONTINUATION = {
    "schema_version": "daily-track-working-state-v1",
    "pending_alpha": [{"session": "2026-08-03"}],
    "rolling_factor": [{"session": "2026-08-03"}],
}


def test_working_cache_loads_verified_state_and_discards_invalid_entries(
    tmp_path: Path,
) -> None:
    cache = _DailyTrackWorkingCache(tmp_path / "cache")
    path = cache.path(TRACK_ID)

    _store(cache)
    assert _load(cache) == CONTINUATION

    damage_cases: tuple[tuple[str, Callable[[Path], None]], ...] = (
        ("missing", lambda target: target.unlink()),
        ("corrupt", lambda target: target.write_text("{", encoding="utf-8")),
        ("stale-basis", lambda target: _replace(target, "basis_sha256", "basis-b")),
        ("stale-head", lambda target: _replace(target, "head_manifest_sha256", "other")),
        ("stale-fence", lambda target: _replace(target, "fence", FENCE - 1)),
        (
            "oversized",
            lambda target: target.write_bytes(b"x" * (MAX_WORKING_CACHE_BYTES + 1)),
        ),
    )
    for _name, damage in damage_cases:
        _store(cache)
        damage(path)
        assert _load(cache) is None
        assert not path.exists()


def _store(cache: _DailyTrackWorkingCache) -> None:
    assert cache.store(
        track_id=TRACK_ID,
        basis_sha256=BASIS_SHA256,
        head_manifest_sha256=HEAD_MANIFEST_SHA256,
        fence=FENCE,
        verified_continuation=CONTINUATION,
    )


def _load(cache: _DailyTrackWorkingCache) -> Mapping[str, object] | None:
    continuation_sha256 = hashlib.sha256(canonical_json_bytes(CONTINUATION)).hexdigest()
    return cache.load(
        track_id=TRACK_ID,
        basis_sha256=BASIS_SHA256,
        head_manifest_sha256=HEAD_MANIFEST_SHA256,
        fence=FENCE,
        continuation_sha256=continuation_sha256,
        pending_alpha_sessions=1,
        rolling_factor_rows=1,
    )


def _replace(path: Path, key: str, value: object) -> None:
    entry = json.loads(path.read_text(encoding="utf-8"))
    entry[key] = value
    path.write_text(json.dumps(entry), encoding="utf-8")
