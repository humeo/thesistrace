"""Replay frozen supplier values without a token, network, or development Dataset."""

from __future__ import annotations

import gzip
import hashlib
import json
import socket
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pytest

from thesistrace.adapters.tushare_benchmark import TushareBenchmarkSource
from thesistrace.adapters.tushare_daily_basic import normalize_daily_basic
from thesistrace.adapters.tushare_industry import TushareIndustrySource
from thesistrace.adapters.tushare_provider import normalize_tushare_snapshot
from thesistrace.data.financial_candidate import (
    FinancialSourceObservation,
    FinancialVersionProjector,
)
from thesistrace.data.financial_indicator_evidence import IndicatorVersionProjector
from thesistrace.data.financial_indicator_series import normalize_indicator_value
from thesistrace.data.source import RawSourceResponse

FIXTURE = Path(__file__).resolve().parents[4] / "tests/fixtures/tushare-recorded-values"
MANIFEST = json.loads((FIXTURE / "manifest.json").read_text())
CONTENT = gzip.decompress((FIXTURE / "samples.json.gz").read_bytes())
assert hashlib.sha256(CONTENT).hexdigest() == MANIFEST["samples_sha256"]
SAMPLES = json.loads(CONTENT)


def ordered(rows):
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def rejected(*args, **kwargs):
        raise AssertionError("Recorded-value regression tests must remain offline")

    monkeypatch.setattr(socket.socket, "connect", rejected)
    monkeypatch.setattr(socket.socket, "connect_ex", rejected)


@pytest.mark.parametrize("case", SAMPLES["market"], ids=lambda case: case["session"])
def test_recorded_market_values_survive_normalization(case) -> None:
    _lineage, canonical = normalize_tushare_snapshot(case["snapshot"])

    # Expected units, adjusted prices and exact decimal rounding are frozen from
    # the source-value audit, not recalculated by the adapter under test.
    assert canonical["research_calendar"] == [case["session"]]
    assert canonical["instruments"] == case["expected_instruments"]
    assert canonical["prices"] == case["expected_prices"]
    assert canonical["price_limits"] == case["expected_limits"]
    assert canonical["trading_states"] == case["expected_states"]
    assert canonical["base_pool"] == case["expected_base_pool"]

    raw = case["daily_basic"]
    actual = normalize_daily_basic(
        RawSourceResponse(tuple(raw["fields"]), tuple(tuple(r) for r in raw["items"])),
        instrument_ids={r["ts_code"]: r["instrument_id"] for r in canonical["instruments"]},
    )
    assert list(actual) == case["expected_daily_basic"]


@pytest.mark.parametrize("case", SAMPLES["statements"], ids=lambda case: case["id"])
@pytest.mark.parametrize("reverse", [False, True], ids=["supplier-order", "reversed-order"])
def test_recorded_statement_versions_preserve_values_and_pit(case, reverse) -> None:
    observations = [
        FinancialSourceObservation(
            endpoint=case["endpoint"],
            instrument_id="equity:" + case["code"],
            ts_code=case["code"],
            source_fields=tuple(receipt["fields"]),
            source_values=tuple(item),
            first_observed_at=receipt["observed_at"],
            raw_batch_sha256=receipt["response_sha256"],
        )
        for receipt in case["receipts"]
        for item in receipt["items"]
    ]
    versions = FinancialVersionProjector().project(
        observations[::-1] if reverse else observations,
        SAMPLES["research_sessions"],
    )
    actual = [
        {
            "source": version.source(),
            "status": version.availability_status,
            "effective_session": version.effective_available_session,
            "revision_basis": version.revision_basis,
        }
        for version in versions
    ]
    assert ordered(actual) == ordered(case["expected_versions"])


@pytest.mark.parametrize("case", SAMPLES["indicators"], ids=lambda case: case["id"])
def test_recorded_indicator_values_preserve_units_nulls_and_pit(case) -> None:
    versions = IndicatorVersionProjector(SAMPLES["research_sessions"]).project(
        [
            {
                "source": "fina_indicator",
                "observed_at": receipt["observed_at"],
                "fields": receipt["fields"],
                "items": receipt["items"],
            }
            for receipt in case["receipts"]
        ],
        instrument_ids={case["code"]: "equity:" + case["code"]},
    )
    actual = [
        {
            "source": {name: row[name] for name in case["receipts"][0]["fields"]},
            "status": row["availability_status"],
            "effective_session": row["effective_available_session"],
        }
        for row in versions
    ]
    assert ordered(actual) == ordered(case["expected_versions"])
    for check in case["normalized_values"]:
        value = normalize_indicator_value(check["source"], source_unit=check["source_unit"])
        assert value == check["expected"]


def test_recorded_industry_intervals_keep_the_inclusive_supplier_end_date() -> None:
    case = SAMPLES["industry"]

    class RecordedProvider:
        def query_paginated(self, api_name, *, params, fields, primary_key):
            if api_name == "index_classify":
                assert params == {"src": "SW2021"}
                return case["classifications"]
            assert api_name == "index_member_all"
            return [r for r in case["memberships"] if r["is_new"] == params["is_new"]]

    actual = TushareIndustrySource(RecordedProvider()).collect(
        allowed_codes=set(case["codes"]),
    )
    assert list(actual.memberships) == case["expected"]


def test_recorded_csi300_benchmark_preserves_all_historical_open_levels() -> None:
    case = SAMPLES["benchmark"]

    class RecordedProvider:
        def query_raw(self, api_name, *, params, fields):
            assert api_name == "index_daily"
            assert params["ts_code"] == "399300.SZ"
            rows = [
                row for row in case["rows"]
                if params["start_date"] <= row["trade_date"] <= params["end_date"]
            ]
            rows = rows[params["offset"]:params["offset"] + params["limit"]]
            return RawSourceResponse(
                tuple(fields), tuple(tuple(row[field] for field in fields) for row in rows),
            )

    actual = TushareBenchmarkSource(RecordedProvider()).collect_open_levels(
        start_session=MANIFEST["coverage_start"], end_session=MANIFEST["coverage_end"],
    )
    assert [(level.session, Decimal(level.open_level)) for level in actual] == [
        (row["session"], Decimal(row["open_level"])) for row in case["expected"]
    ]


def test_frozen_sample_covers_every_dataset_year_and_financial_family() -> None:
    expected_years = set(range(2010, 2027))
    assert {int(case["session"][:4]) for case in SAMPLES["market"]} == expected_years
    years_by_endpoint = defaultdict(set)
    for case in [*SAMPLES["statements"], *SAMPLES["indicators"]]:
        years_by_endpoint[case["endpoint"]].add(int(case["period"][:4]))
    assert set(years_by_endpoint) == {"income", "balancesheet", "cashflow", "fina_indicator"}
    assert all(expected_years <= years for years in years_by_endpoint.values())
    assert MANIFEST["automatic_refresh"] is False
