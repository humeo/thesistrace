from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from typing import Protocol

from thesistrace.adapters.tushare_data import TushareDataSource
from thesistrace.adapters.tushare_provider import HttpTushareTransport, TushareAdapter
from thesistrace.data import bootstrap_collection_plan


class LiveGateProvider(Protocol):
    def preflight(self) -> None: ...

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
        token = os.environ.get("TUSHARE_TOKEN", "").strip()
        if not token:
            raise SystemExit("TUSHARE_TOKEN is required for the live Tushare gate")
        transport = HttpTushareTransport()
        provider = TushareAdapter(token=token, transport=transport)
    try:
        provider.preflight()
        batch = TushareDataSource(provider=provider).collect_bootstrap(
            bootstrap_collection_plan(as_of or datetime.now(UTC))
        )
    finally:
        if transport is not None:
            transport.close()
    print(
        json.dumps(
            {
                "canonical_schema": batch.canonical["schema_version"],
                "covered_session_range": batch.covered_session_range,
                "research_session_count": len(batch.canonical["research_calendar"]),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
