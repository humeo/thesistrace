from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


class IndustrySourceError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        diagnostic: Mapping[str, object] | None = None,
        source_lineage_sha256: str | None = None,
        raw_payload: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.diagnostic = dict(diagnostic or {})
        self.source_lineage_sha256 = source_lineage_sha256
        self.raw_payload = None if raw_payload is None else dict(raw_payload)


@dataclass(frozen=True)
class IndustrySourceSnapshot:
    memberships: tuple[dict[str, str], ...]
    raw_classifications: tuple[dict[str, object], ...]
    raw_memberships: tuple[dict[str, object], ...]
    source_lineage_sha256: str

    def raw_payload(self) -> dict[str, object]:
        return {
            "source": "tushare",
            "source_contract_version": "tushare-industry-v1",
            "classification_version": "SW2021",
            "classifications": list(self.raw_classifications),
            "memberships": list(self.raw_memberships),
        }


class IndustrySource(Protocol):
    def collect(self, *, allowed_codes: set[str]) -> IndustrySourceSnapshot: ...


def industry_source_payload_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


__all__ = (
    "IndustrySource",
    "IndustrySourceError",
    "IndustrySourceSnapshot",
    "industry_source_payload_bytes",
)
