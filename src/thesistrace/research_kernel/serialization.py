"""Canonical serialization used only to define Kernel checksums."""

import hashlib
import json
from collections.abc import Iterable


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_checksum_chain(values: Iterable[object]) -> str:
    prior: bytes | None = None
    for value in values:
        checksum = hashlib.sha256()
        if prior is not None:
            checksum.update(prior)
        checksum.update(canonical_json_bytes(value))
        prior = checksum.digest()
    return (prior or hashlib.sha256(b"").digest()).hex()
