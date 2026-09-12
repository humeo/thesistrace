from decimal import Decimal

import pytest


def test_holding_partitions_preserve_values_and_empty_session_coverage():
    from thesistrace.daily_holding_evidence import (
        HoldingEvidencePublication,
        read_holding_partition,
    )
    from thesistrace.publication import JsonPayload
    from thesistrace.publication.serialization import parquet_bytes

    builder = HoldingEvidencePublication()
    rows = [
        {"session": "2026-01-06", "instrument_id": f"equity:{index:06d}.SH",
         "execution_shares": 100, "adjusted_units": "50", "adjusted_mark": "20",
         "market_value_cny": "1000", "weight": 0.001}
        for index in range(600)
    ]
    builder.add_segment(["2026-01-05", "2026-01-06"], rows)
    payloads = builder.finish()
    assert isinstance(payloads["daily_holdings"], JsonPayload)
    coverage = payloads["daily_holdings"].value
    assert coverage["sessions"] == ["2026-01-05", "2026-01-06"]
    assert [part["row_count"] for part in coverage["parts"]] == [512, 88]
    decoded = []
    for part in coverage["parts"]:
        payload = payloads[part["name"]]
        decoded.extend(read_holding_partition(parquet_bytes(payload.rows, payload.contract)))
    assert decoded == rows
    assert sum(Decimal(row["market_value_cny"]) for row in decoded) == Decimal("600000")
    with pytest.raises(ValueError, match="overlap"):
        builder.add_segment(["2026-01-06"], [])


def test_holding_coverage_rejects_outside_rows_and_accepts_complete_empty_account():
    from thesistrace.daily_holding_evidence import HoldingEvidencePublication

    builder = HoldingEvidencePublication()
    builder.add_segment(["2026-01-05"], [])
    payloads = builder.finish()
    assert set(payloads) == {"daily_holdings"}
    assert payloads["daily_holdings"].value["parts"] == []
    with pytest.raises(ValueError, match="coverage"):
        builder.add_segment(["2026-01-06"], [{"session": "2026-01-07"}])
