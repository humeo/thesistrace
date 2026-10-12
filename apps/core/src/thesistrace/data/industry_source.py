from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from thesistrace.industry_catalog import SW2021_L1


def validate_industry_membership_codes(rows: Sequence[Mapping[str, object]]) -> None:
    for row in rows:
        codes = [row.get(field) for field in ("sw2021_l1", "sw2021_l2", "sw2021_l3")]
        if (
            any(
                not isinstance(code, str)
                or len(code) != 6
                or not code.isascii()
                or not code.isdigit()
                for code in codes
            )
            or codes[0] not in SW2021_L1
        ):
            raise ValueError("Canonical Industry Membership codes are invalid")


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
    "validate_industry_membership_codes",
)
