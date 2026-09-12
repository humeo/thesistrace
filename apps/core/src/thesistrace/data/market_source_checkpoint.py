"""Validated price observations retained across one interrupted refresh."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from thesistrace.data.generation_files import AddressedFileError, AddressedFileStore
from thesistrace.data.source import DataSourceError
from thesistrace.publication.serialization import canonical_json_bytes


class MarketSourceCheckpoint:
    def __init__(self, root: Path, *, request: dict[str, str]) -> None:
        self._request = request
        self._directory = root / "price" / hashlib.sha256(canonical_json_bytes(request)).hexdigest()
        self._files = AddressedFileStore(root)

    def load(self) -> dict[str, list[dict[str, object]]] | None:
        try:
            paths = tuple(self._directory.glob("*.json"))
            if not paths:
                return None
            if len(paths) != 1:
                raise ValueError("Conflicting price observations")
            path = paths[0]
            payload = json.loads(self._files.read(
                path, path.stem, max_byte_count=128 * 1024 * 1024,
            ))
            if (set(payload) != {"request", "observed_at", "snapshot"}
                    or payload["request"] != self._request
                    or datetime.fromisoformat(payload["observed_at"]).tzinfo is None):
                raise ValueError("Invalid price receipt")
            return payload["snapshot"]
        except (AddressedFileError, OSError, ValueError, KeyError, TypeError) as error:
            raise DataSourceError(
                "invalid_source_data", detail_code="PRICE_CHECKPOINT_INVALID",
            ) from error

    def save(self, snapshot: dict[str, list[dict[str, object]]]) -> None:
        content = canonical_json_bytes({
            "request": self._request, "observed_at": datetime.now(UTC).isoformat(),
            "snapshot": snapshot,
        })
        if len(content) > 128 * 1024 * 1024:
            raise DataSourceError("invalid_source_data", detail_code="PRICE_RECEIPT_TOO_LARGE")
        digest = hashlib.sha256(content).hexdigest()
        try:
            self._files.store(self._directory / f"{digest}.json", digest, content)
        except AddressedFileError as error:
            raise DataSourceError(
                "unavailable", detail_code="PRICE_CHECKPOINT_WRITE_FAILED",
            ) from error
