from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Protocol

from thesistrace.adapters.tushare_provider import TushareSourceError, iso_date
from thesistrace.data.industry_source import (
    IndustrySourceError,
    IndustrySourceSnapshot,
    industry_source_payload_bytes,
)

INDUSTRY_SOURCE_CONTRACT_VERSION = "tushare-industry-v1"
_CLASSIFICATION_FIELDS = ("index_code", "industry_name", "level", "src")
_MEMBERSHIP_FIELDS = (
    "l1_code",
    "l2_code",
    "l3_code",
    "ts_code",
    "in_date",
    "out_date",
    "is_new",
)


class PaginatedIndustryProvider(Protocol):
    def query_paginated(
        self,
        api_name: str,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
        primary_key: Sequence[str],
    ) -> list[dict[str, object]]: ...


class TushareIndustrySource:
    def __init__(self, provider: PaginatedIndustryProvider) -> None:
        self._provider = provider

    def collect(self, *, allowed_codes: set[str]) -> IndustrySourceSnapshot:
        try:
            classifications = self._provider.query_paginated(
                "index_classify",
                params={"src": "SW2021"},
                fields=_CLASSIFICATION_FIELDS,
                primary_key=("index_code",),
            )
            memberships = self._provider.query_paginated(
                "index_member_all",
                params={},
                fields=_MEMBERSHIP_FIELDS,
                primary_key=("ts_code", "in_date", "l3_code", "is_new"),
            )
        except TushareSourceError as error:
            raise IndustrySourceError(error.reason_code) from error
        if not classifications or not memberships:
            raise IndustrySourceError("INDUSTRY_CAPABILITY_UNAVAILABLE")
        payload = {
            "source": "tushare",
            "source_contract_version": INDUSTRY_SOURCE_CONTRACT_VERSION,
            "classification_version": "SW2021",
            "classifications": classifications,
            "memberships": memberships,
        }
        source_lineage_sha256 = hashlib.sha256(industry_source_payload_bytes(payload)).hexdigest()
        try:
            normalized = _normalize_primary_classification(
                memberships,
                allowed_codes=allowed_codes,
            )
        except IndustrySourceError as error:
            raise IndustrySourceError(
                error.code,
                diagnostic=error.diagnostic,
                source_lineage_sha256=source_lineage_sha256,
                raw_payload=payload,
            ) from error
        return IndustrySourceSnapshot(
            memberships=tuple(normalized),
            raw_classifications=tuple(dict(row) for row in classifications),
            raw_memberships=tuple(dict(row) for row in memberships),
            source_lineage_sha256=source_lineage_sha256,
        )


def _normalize_primary_classification(
    rows: Sequence[Mapping[str, object]],
    *,
    allowed_codes: set[str],
) -> list[dict[str, str]]:
    intervals = [
        {
            "instrument_id": f"equity:{row['ts_code']}",
            "active_from": iso_date(str(row["in_date"])),
            "active_to": iso_date(str(row["out_date"])) if row.get("out_date") else "",
            "sw2021_l1": str(row.get("l1_code", "")),
            "sw2021_l2": str(row.get("l2_code", "")),
            "sw2021_l3": str(row.get("l3_code", "")),
        }
        for row in rows
        if row.get("ts_code")
        and str(row["ts_code"]) in allowed_codes
        and row.get("in_date")
    ]
    intervals.sort(
        key=lambda item: (
            item["instrument_id"],
            item["active_from"],
            item["active_to"],
            item["sw2021_l1"],
            item["sw2021_l2"],
            item["sw2021_l3"],
        )
    )
    previous: dict[str, dict[str, str]] = {}
    overlaps: list[dict[str, str]] = []
    for interval in intervals:
        prior = previous.get(interval["instrument_id"])
        if prior is not None and interval["active_from"] < (
            prior["active_to"] or "9999-12-31"
        ):
            overlaps.append({"prior_from": prior["active_from"], **interval})
        if prior is None or (interval["active_to"] or "9999-12-31") > (
            prior["active_to"] or "9999-12-31"
        ):
            previous[interval["instrument_id"]] = interval
    if overlaps:
        raise IndustrySourceError(
            "OVERLAPPING_PRIMARY_INDUSTRY_CLASSIFICATION",
            diagnostic={
                "instrument_id": overlaps[0]["instrument_id"],
                "overlap_count": len(overlaps),
                "examples": overlaps[:4],
            },
        )
    return intervals


__all__ = (
    "INDUSTRY_SOURCE_CONTRACT_VERSION",
    "IndustrySourceError",
    "IndustrySourceSnapshot",
    "PaginatedIndustryProvider",
    "TushareIndustrySource",
)
