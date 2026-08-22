from __future__ import annotations

import hashlib

from thesistrace.data.daily_financial_refresh import (
    FinancialTriggerResolver,
    PendingFinancialTrigger,
)
from thesistrace.data.financial_collection import (
    FINANCIAL_ENDPOINTS,
    FinancialShardCheckpoint,
    RawFinancialBatchStore,
)
from thesistrace.publication.serialization import canonical_json_bytes


def test_trigger_resolution_requires_a_known_matching_report_period(tmp_path) -> None:
    fields = ("ts_code", "ann_date", "f_ann_date", "end_date")
    items = (("000001.SZ", "20260818", "", "20260630"),)
    payload_sha256 = hashlib.sha256(
        canonical_json_bytes({"fields": list(fields), "items": [list(items[0])]})
    ).hexdigest()
    store = RawFinancialBatchStore(tmp_path)
    checkpoints: list[FinancialShardCheckpoint] = []
    for endpoint in FINANCIAL_ENDPOINTS:
        payload = {
            "format": "thesistrace-raw-financial-batch",
            "version": 1,
            "source_contract_version": "tushare-financial-ordinary-v2",
            "endpoint": endpoint,
            "parameters": {"ts_code": "000001.SZ"},
            "returned_fields": list(fields),
            "items": [list(items[0])],
            "row_count": 1,
            "source_date_extent": ["20260818", "20260818"],
            "payload_sha256": payload_sha256,
        }
        checkpoints.append(
            FinancialShardCheckpoint(
                ordinal=len(checkpoints),
                endpoint=endpoint,
                instrument_id="equity:000001.SZ",
                ts_code="000001.SZ",
                shard="complete-history",
                status="completed",
                batch_sha256=store.store(canonical_json_bytes(payload)),
                collected_at="2026-08-18T10:00:00+00:00",
                first_observed_at="2026-08-18T10:00:00+00:00",
            )
        )

    matched = FinancialTriggerResolver(tmp_path).matching_announcement_ids(
        checkpoints=tuple(checkpoints),
        triggers=(
            PendingFinancialTrigger(
                announcement_id="a" * 64,
                instrument_id="equity:000001.SZ",
                ts_code="000001.SZ",
                source_published_date="2026-08-18",
                report_period="2026-06-30",
            ),
            PendingFinancialTrigger(
                announcement_id="b" * 64,
                instrument_id="equity:000001.SZ",
                ts_code="000001.SZ",
                source_published_date="2026-08-18",
                report_period=None,
            ),
        ),
    )

    assert matched == ("a" * 64,)
