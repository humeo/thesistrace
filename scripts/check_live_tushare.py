from __future__ import annotations

import json
import os

from thesistrace.adapters.tushare_data import TushareDataSource
from thesistrace.adapters.tushare_provider import HttpTushareTransport, TushareAdapter
from thesistrace.data import CollectionPlan


def main() -> None:
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise SystemExit("TUSHARE_TOKEN is required for the live Tushare gate")
    transport = HttpTushareTransport()
    try:
        provider = TushareAdapter(token=token, transport=transport)
        provider.preflight()
        batch = TushareDataSource(provider=provider).collect(
            CollectionPlan.bootstrap()
        )
    finally:
        transport.close()
    print(
        json.dumps(
            {
                "canonical_schema": batch.canonical["schema_version"],
                "covered_session_range": batch.covered_session_range,
                "research_session_count": len(
                    batch.canonical["research_calendar"]
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
