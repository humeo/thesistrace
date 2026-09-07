from __future__ import annotations

import json
import os
import sys
from datetime import UTC, date, datetime
from typing import Protocol

from thesistrace.adapters.tushare_data import TushareDataSource
from thesistrace.adapters.tushare_provider import (
    HttpTushareTransport,
    TushareAdapter,
    TushareSourceError,
)
from thesistrace.data import DataSourceError, bootstrap_collection_plan


class LiveGateProvider(Protocol):
    def preflight(self) -> dict[str, object]: ...

    def collect_bootstrap_snapshot(
        self,
        *,
        start_date: date,
        completed_through_date: date,
    ) -> dict[str, list[dict[str, object]]]: ...


def main(
    *,
    provider: LiveGateProvider | None = None,
    as_of: datetime | None = None,
) -> None:
    transport: HttpTushareTransport | None = None
    if provider is None:
        token = os.environ.get("THESISTRACE_TUSHARE_TOKEN", "").strip()
        if not token:
            raise SystemExit("THESISTRACE_TUSHARE_TOKEN is required for the live Tushare gate")
        transport = HttpTushareTransport()
        provider = TushareAdapter(token=token, transport=transport, progress=_print_progress)
    try:
        try:
            preflight = provider.preflight()
        except TushareSourceError as error:
            _print_report(
                {
                    "status": "failed",
                    "failed_check": "provider_preflight",
                    "error": error.diagnostic(),
                }
            )
            raise SystemExit(1) from None
        try:
            batch = TushareDataSource(provider=provider).collect_bootstrap(
                bootstrap_collection_plan(as_of or datetime.now(UTC))
            )
        except DataSourceError as error:
            diagnostic: dict[str, object] = {
                "category": error.category,
                "reason_code": error.detail_code,
            }
            if isinstance(error.__cause__, TushareSourceError):
                diagnostic.update(error.__cause__.diagnostic())
            _print_report(
                {
                    "status": "failed",
                    "failed_check": "bootstrap_collection",
                    "provider_preflight": preflight,
                    "error": diagnostic,
                }
            )
            raise SystemExit(1) from None
    finally:
        if transport is not None:
            transport.close()
    _print_report(
        {
            "status": "passed",
            "provider_preflight": preflight,
            "bootstrap_collection": {
                "status": "passed",
                "canonical_schema": batch.canonical["schema_version"],
                "covered_session_range": batch.covered_session_range,
                "research_session_count": len(batch.canonical["research_calendar"]),
            },
        }
    )


def _print_report(report: dict[str, object]) -> None:
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


def _print_progress(event: dict[str, object]) -> None:
    print(
        json.dumps(event, ensure_ascii=False, sort_keys=True),
        file=sys.stderr,
        flush=True,
    )
