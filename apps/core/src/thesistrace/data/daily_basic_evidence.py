"""Retained daily source observations and their immutable evidence indexes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from thesistrace.data.generation_files import AddressedFileError, AddressedFileStore
from thesistrace.data.source import DataSourceError, RawSourceResponse
from thesistrace.publication.serialization import canonical_json_bytes

# Raw observations are retained append-only, outside derived Generation garbage collection.
# Operator and refresh writers hold the mounted-data mutation lock while populating this store.
MARKET_SOURCE_RECEIPT_DIRECTORY = ".operator/market-source-receipts"

def daily_basic_evidence_path(collection_key: str, digest: str) -> Path:
    """Return the sole canonical relative address of a daily evidence manifest."""
    if (not collection_key or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)):
        raise ValueError("Invalid daily evidence identity")
    operation = hashlib.sha256(collection_key.encode()).hexdigest()
    return Path(operation) / "evidence" / "sha256" / f"{digest}.json"


class DailyBasicCheckpoint:
    """Immutable successful request receipts, isolated by refresh operation.

    A capped whole-day receipt is reusable evidence, not completion of that day.
    The collector must still finish every security shard before it returns.
    New refresh operations use a new key so overlap days are observed again.
    """

    def __init__(self, root: Path, *, collection_key: str) -> None:
        if not collection_key:
            raise ValueError("Daily basic checkpoint requires a collection key")
        self._root = root
        self._collection_key = collection_key
        self._directory = root / hashlib.sha256(collection_key.encode()).hexdigest()
        self._files = AddressedFileStore(root)
        self._completed_sessions: set[str] = set()
        self._used_receipts: set[Path] = set()

    def mark_session_collected(self, session: str) -> None:
        """Record completion after the source has exhausted every required shard."""
        if date.fromisoformat(session).isoformat() != session:
            raise ValueError("Collected session must be an ISO date")
        self._completed_sessions.add(session)

    def _request_directory(self, request: Mapping[str, object]) -> Path:
        return self._directory / hashlib.sha256(canonical_json_bytes(request)).hexdigest()

    def load(self, request: Mapping[str, object]) -> RawSourceResponse | None:
        try:
            paths = tuple(self._request_directory(request).glob("*.json"))
            if not paths:
                return None
            if len(paths) != 1:
                raise ValueError("Daily basic checkpoint has conflicting observations")
            payload = self._read(paths[0])
            if payload["request"] != request:
                raise ValueError("Daily basic checkpoint scope differs")
            response = payload["response"]
            self._used_receipts.add(paths[0])
            return RawSourceResponse(
                fields=tuple(response["fields"]),
                items=tuple(tuple(row) for row in response["items"]),
            )
        except (AddressedFileError, OSError, ValueError, KeyError, TypeError) as error:
            raise DataSourceError(
                "invalid_source_data", detail_code="DAILY_BASIC_CHECKPOINT_INVALID",
            ) from error

    def save(self, request: Mapping[str, object], raw: RawSourceResponse) -> None:
        payload = {
            "collection_key": self._collection_key,
            "request": dict(request),
            "observed_at": datetime.now(UTC).isoformat(),
            "response": {"fields": raw.fields, "items": raw.items},
        }
        content = canonical_json_bytes(payload)
        if len(content) > 32 * 1024 * 1024:
            raise DataSourceError(
                "invalid_source_data", detail_code="DAILY_BASIC_RECEIPT_TOO_LARGE",
            )
        digest = hashlib.sha256(content).hexdigest()
        try:
            path = self._request_directory(request) / f"{digest}.json"
            self._files.store(path, digest, content)
            self._used_receipts.add(path)
        except AddressedFileError as error:
            raise DataSourceError(
                "unavailable", detail_code="DAILY_BASIC_CHECKPOINT_WRITE_FAILED",
            ) from error

    def _read(self, path: Path) -> dict[str, object]:
        payload = json.loads(self._files.read(path, path.stem, max_byte_count=32 * 1024 * 1024))
        if (
            not isinstance(payload, dict)
            or set(payload) != {"collection_key", "request", "observed_at", "response"}
            or payload["collection_key"] != self._collection_key
            or datetime.fromisoformat(payload["observed_at"]).tzinfo is None
        ):
            raise ValueError("Daily basic receipt is invalid")
        return payload

    def evidence(self) -> tuple[dict[str, object], ...]:
        """Return source receipt coordinates for the candidate's lineage."""
        try:
            return tuple({
                "sha256": path.stem,
                "path": str(path.relative_to(self._root)),
                "request": self._read(path)["request"],
            } for path in sorted(self._directory.glob("*/*.json")))
        except (AddressedFileError, OSError, ValueError, KeyError, TypeError) as error:
            raise DataSourceError(
                "invalid_source_data", detail_code="DAILY_BASIC_CHECKPOINT_INVALID",
            ) from error

    def seal(self, sessions: Sequence[str]) -> dict[str, str]:
        """Bind completed dates to paged immutable raw receipt references."""
        if (
            not sessions or tuple(sessions) != tuple(sorted(set(sessions)))
            or set(sessions) != self._completed_sessions
        ):
            raise DataSourceError(
                "invalid_source_data", detail_code="DAILY_BASIC_COLLECTION_INCOMPLETE",
            )
        try:
            pages: list[dict[str, str]] = []
            page: list[dict[str, str]] = []
            for path in sorted(self._used_receipts):
                payload = self._read(path)
                request = payload["request"]
                if self._request_directory(request) != path.parent:
                    raise ValueError("Receipt request address differs")
                page.append({"path": str(path.relative_to(self._root)), "sha256": path.stem})
                if len(page) == 256:
                    pages.append(self._store_evidence({"receipts": page}))
                    page = []
            if page:
                pages.append(self._store_evidence({"receipts": page}))
            if not pages:
                raise ValueError("Completed collection has no receipts")
            return self._store_evidence({
                "collection_key": self._collection_key, "sessions": list(sessions), "pages": pages,
            })
        except (AddressedFileError, OSError, ValueError, KeyError, TypeError) as error:
            raise DataSourceError(
                "invalid_source_data", detail_code="DAILY_BASIC_EVIDENCE_INVALID",
            ) from error

    def verify_evidence(self, reference: Mapping[str, str]) -> tuple[str, ...]:
        """Reopen the evidence and checksum every raw observation it references."""
        try:
            manifest = self._read_evidence(reference)
            if (
                set(manifest) != {"collection_key", "sessions", "pages"}
                or manifest["collection_key"] != self._collection_key
                or not isinstance(manifest["sessions"], list)
                or not manifest["sessions"]
                or manifest["sessions"] != sorted(set(manifest["sessions"]))
                or not isinstance(manifest["pages"], list) or not manifest["pages"]
            ):
                raise ValueError("Invalid collection evidence")
            expected = {date.fromisoformat(value).strftime("%Y%m%d")
                        for value in manifest["sessions"]}
            observed: set[str] = set()
            seen: set[str] = set()
            for page_ref in manifest["pages"]:
                page = self._read_evidence(page_ref)
                receipts = page.get("receipts")
                if set(page) != {"receipts"} or not isinstance(receipts, list) or not (
                    1 <= len(receipts) <= 256
                ):
                    raise ValueError("Invalid evidence page")
                for receipt in receipts:
                    if set(receipt) != {"path", "sha256"}:
                        raise ValueError("Invalid receipt reference")
                    path = self._root / receipt["path"]
                    if path.stem != receipt["sha256"] or str(path) in seen:
                        raise ValueError("Duplicate or mismatched receipt")
                    payload = self._read(path)
                    if self._request_directory(payload["request"]) != path.parent:
                        raise ValueError("Receipt request address differs")
                    observed.add(payload["request"]["params"]["trade_date"])
                    seen.add(str(path))
            if observed != expected:
                raise ValueError("Evidence dates differ from completed dates")
            return tuple(manifest["sessions"])
        except (AddressedFileError, OSError, ValueError, KeyError, TypeError) as error:
            raise DataSourceError(
                "invalid_source_data", detail_code="DAILY_BASIC_EVIDENCE_INVALID",
            ) from error

    def _store_evidence(self, value: Mapping[str, object]) -> dict[str, str]:
        content = canonical_json_bytes(value)
        if len(content) > 4 * 1024 * 1024:
            raise ValueError("Evidence manifest exceeds its bound")
        digest = hashlib.sha256(content).hexdigest()
        path = self._root / daily_basic_evidence_path(self._collection_key, digest)
        self._files.store(path, digest, content)
        return {"path": str(path.relative_to(self._root)), "sha256": digest}

    def _read_evidence(self, reference: Mapping[str, str]) -> dict[str, object]:
        if set(reference) != {"path", "sha256"}:
            raise ValueError("Invalid evidence reference")
        digest = reference["sha256"]
        path = self._root / daily_basic_evidence_path(self._collection_key, digest)
        if reference["path"] != str(path.relative_to(self._root)):
            raise ValueError("Evidence address differs")
        value = json.loads(self._files.read(path, digest, max_byte_count=4 * 1024 * 1024))
        if not isinstance(value, dict):
            raise ValueError("Evidence must be an object")
        return value
