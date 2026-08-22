from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from thesistrace.publication.serialization import canonical_json_bytes

FINANCIAL_ANNOUNCEMENT_CATEGORIES = (
    "年报",
    "半年报",
    "一季报",
    "三季报",
    "补充更正",
)


@dataclass(frozen=True)
class FinancialAnnouncement:
    announcement_id: str
    category: str
    ts_code: str
    name: str
    title: str
    source_published_date: str
    report_period: str | None
    url: str


@dataclass(frozen=True)
class FinancialDiscoveryGap:
    category: str
    start_date: str
    end_date: str
    failure_code: str


@dataclass(frozen=True)
class FinancialAnnouncementDiscovery:
    start_date: str
    end_date: str
    completed_categories: tuple[str, ...]
    announcements: tuple[FinancialAnnouncement, ...]
    gaps: tuple[FinancialDiscoveryGap, ...]
    source_lineage_sha256: str


class FinancialAnnouncementSource(Protocol):
    def discover(
        self,
        *,
        start_date: str,
        end_date: str,
        allowed_ts_codes: set[str] | frozenset[str],
    ) -> FinancialAnnouncementDiscovery: ...


def financial_announcement_id(
    *,
    category: str,
    ts_code: str,
    name: str,
    title: str,
    source_published_date: str,
    url: str,
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "category": category,
                "ts_code": ts_code,
                "name": name,
                "title": title,
                "source_published_date": source_published_date,
                "url": url,
            }
        )
    ).hexdigest()


def financial_discovery_lineage_sha256(
    *,
    start_date: str,
    end_date: str,
    completed_categories: tuple[str, ...],
    announcement_ids: tuple[str, ...],
    gaps: tuple[FinancialDiscoveryGap, ...],
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "source": "cninfo-via-akshare",
                "start_date": start_date,
                "end_date": end_date,
                "completed_categories": completed_categories,
                "announcement_ids": announcement_ids,
                "gaps": [gap.__dict__ for gap in gaps],
            }
        )
    ).hexdigest()


__all__ = (
    "FINANCIAL_ANNOUNCEMENT_CATEGORIES",
    "FinancialAnnouncement",
    "FinancialAnnouncementDiscovery",
    "FinancialAnnouncementSource",
    "FinancialDiscoveryGap",
    "financial_announcement_id",
    "financial_discovery_lineage_sha256",
)
