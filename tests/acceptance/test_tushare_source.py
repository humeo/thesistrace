from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.fixture import adjustment_factor, build_fixture, decimal_string, price_rows
from thesistrace.objects import ImmutableObjectStore
from thesistrace.storage import MetadataStore
from thesistrace.tushare_source import (
    TushareAdapter,
    TushareSourceError,
    normalize_tushare_increment,
    normalize_tushare_snapshot,
)


class RecordingTransport:
    def __init__(self, denied_api: str | None = None) -> None:
        self.denied_api = denied_api
        self.payloads: list[dict[str, object]] = []

    def post(self, payload: Mapping[str, object]) -> dict[str, object]:
        copied = dict(payload)
        self.payloads.append(copied)
        if payload["api_name"] == self.denied_api:
            return {"code": 2002, "msg": "permission denied", "data": None}
        return {
            "code": 0,
            "msg": "",
            "data": {
                "fields": ["ts_code", "trade_date"],
                "items": [["600000.SH", "20260729"]],
            },
        }


def test_tushare_preflight_checks_all_permissions_without_exposing_token(tmp_path: Path) -> None:
    transport = RecordingTransport()
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        tushare_token="deployment-secret-token",
    )

    with TestClient(create_app(settings, tushare_transport=transport)) as client:
        response = client.post("/api/v1/sources/tushare/preflight")

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "available"
    assert result["source"] == "tushare"
    assert result["source_contract_version"] == "tushare-v1"
    assert {item["contract"] for item in result["permissions"]} == {
        "reference",
        "calendar_sse",
        "calendar_szse",
        "daily",
        "adjustment",
        "suspension",
        "st",
        "price_limit",
        "sw2021_classification",
        "sw2021_membership",
    }
    assert all(item["status"] == "available" for item in result["permissions"])
    assert "deployment-secret-token" not in response.text
    assert all(payload["token"] == "deployment-secret-token" for payload in transport.payloads)


def test_missing_permission_is_reason_coded_and_publishes_nothing(tmp_path: Path) -> None:
    transport = RecordingTransport(denied_api="stock_st")
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        tushare_token="deployment-secret-token",
    )

    with TestClient(create_app(settings, tushare_transport=transport)) as client:
        response = client.post("/api/v1/sources/tushare/preflight")
        workspace = client.get("/api/v1/workspace").json()

    assert response.status_code == 424
    assert response.json()["detail"] == {
        "reason_code": "MISSING_PERMISSION",
        "contract": "st",
        "source_code": 2002,
    }
    assert workspace["resource_counts"]["dataset_releases"] == 0
    assert "deployment-secret-token" not in response.text


def test_adapter_paginates_deduplicates_and_sorts_deterministically() -> None:
    class PagingTransport:
        def __init__(self) -> None:
            self.offsets: list[int] = []

        def post(self, payload: Mapping[str, object]) -> dict[str, object]:
            params = dict(payload["params"])
            offset = int(params["offset"])
            self.offsets.append(offset)
            pages = {
                0: [["600002.SH", "20260729"], ["600001.SH", "20260729"]],
                2: [["600001.SH", "20260729"], ["600003.SH", "20260729"]],
                4: [],
            }
            return {
                "code": 0,
                "msg": "",
                "data": {
                    "fields": ["ts_code", "trade_date"],
                    "items": pages[offset],
                },
            }

    transport = PagingTransport()
    adapter = TushareAdapter(
        token="secret",
        transport=transport,
        page_size=2,
        throttle_seconds=0,
    )
    rows = adapter.query_paginated(
        "daily",
        params={"trade_date": "20260729"},
        fields=("ts_code", "trade_date"),
        primary_key=("trade_date", "ts_code"),
    )

    assert transport.offsets == [0, 2, 4]
    assert rows == [
        {"ts_code": "600001.SH", "trade_date": "20260729"},
        {"ts_code": "600002.SH", "trade_date": "20260729"},
        {"ts_code": "600003.SH", "trade_date": "20260729"},
    ]


def test_adjustment_anchor_search_continues_past_the_first_window() -> None:
    class DelayedAnchorTransport:
        def post(self, payload: Mapping[str, object]) -> dict[str, object]:
            params = dict(payload["params"])
            fields = str(payload["fields"]).split(",")
            second_window = str(params.get("start_date", "")) > "20260101"
            item: list[object] | None = None
            if second_window and payload["api_name"] == "daily":
                values = {
                    "ts_code": "600000.SH",
                    "trade_date": "20260220",
                    "open": "10",
                    "high": "11",
                    "low": "9",
                    "close": "10.5",
                    "pre_close": "10",
                    "change": "0.5",
                    "pct_chg": "5",
                    "vol": "100",
                    "amount": "1000",
                }
                item = [values[field] for field in fields]
            if second_window and payload["api_name"] == "adj_factor":
                values = {
                    "ts_code": "600000.SH",
                    "trade_date": "20260220",
                    "adj_factor": "1",
                }
                item = [values[field] for field in fields]
            return {
                "code": 0,
                "msg": "",
                "data": {"fields": fields, "items": [] if item is None else [item]},
            }

    adapter = TushareAdapter(
        token="secret",
        transport=DelayedAnchorTransport(),
        throttle_seconds=0,
    )
    daily, adjustments = adapter._collect_adjustment_anchors(
        [
            {
                "ts_code": "600000.SH",
                "exchange": "SSE",
                "market": "主板",
                "list_date": "20260101",
                "delist_date": "",
            }
        ],
        date(2026, 3, 31),
    )
    assert daily[0]["trade_date"] == "20260220"
    assert adjustments[0]["trade_date"] == "20260220"


def test_http_statuses_retry_and_decimal_non_finite_values_are_reason_coded() -> None:
    class UnavailableTransport:
        def __init__(self) -> None:
            self.calls = 0

        def post(self, payload: Mapping[str, object]) -> dict[str, object]:
            self.calls += 1
            request = httpx.Request("POST", "https://api.tushare.pro")
            response = httpx.Response(503, request=request)
            raise httpx.HTTPStatusError("unavailable", request=request, response=response)

    transport = UnavailableTransport()
    adapter = TushareAdapter(
        token="secret",
        transport=transport,
        throttle_seconds=0,
        max_attempts=3,
    )
    with pytest.raises(TushareSourceError) as unavailable:
        adapter.query("daily", params={}, fields=("ts_code",))
    assert unavailable.value.diagnostic() == {
        "reason_code": "UPSTREAM_UNAVAILABLE",
        "source_code": 503,
    }
    assert transport.calls == 3


def test_live_normalizer_feeds_the_same_atomic_publication_boundary(tmp_path: Path) -> None:
    fixture_source, fixture_canonical = build_fixture()
    code_by_instrument = {
        item["instrument_id"]: item["ts_code"] for item in fixture_source["instruments"]
    }
    snapshot = {
        "calendar_sse": [
            {"exchange": "SSE", "cal_date": compact(day), "is_open": "1"}
            for day in fixture_source["sse_open_days"]
        ],
        "calendar_szse": [
            {"exchange": "SZSE", "cal_date": compact(day), "is_open": "1"}
            for day in fixture_source["szse_open_days"]
        ],
        "stock_basic": [
            {
                "ts_code": item["ts_code"],
                "exchange": item["exchange"],
                "market": "创业板" if item["board"] == "chinext" else "主板",
                "list_date": compact(item["listed_from"]),
                "delist_date": "",
            }
            for item in fixture_source["instruments"]
        ],
        "daily": [
            {**row, "trade_date": compact(row["trade_date"])} for row in fixture_source["daily"]
        ],
        "adjustments": [
            {**row, "trade_date": compact(row["trade_date"])}
            for row in fixture_source["adjustments"]
        ],
        "anchor_daily": [
            {**row, "trade_date": compact(row["trade_date"])}
            for row in fixture_source["daily"]
            if row["trade_date"] == fixture_source["sse_open_days"][0]
        ],
        "anchor_adjustments": [
            {**row, "trade_date": compact(row["trade_date"])}
            for row in fixture_source["adjustments"]
            if row["trade_date"] == fixture_source["sse_open_days"][0]
        ],
        "suspensions": [
            {
                "ts_code": code_by_instrument[state["instrument_id"]],
                "trade_date": compact(state["session"]),
                "suspend_timing": {
                    "full_session_suspension": "全天",
                    "partial_opening_suspension": "09:30-10:30",
                    "after_open_suspension": "13:00-15:00",
                }[state["state"]],
                "suspend_type": "S",
            }
            for state in fixture_canonical["trading_states"]
            if state["state"] != "normal"
        ],
        "st": [],
        "price_limits": [
            {
                "ts_code": code_by_instrument[item["instrument_id"]],
                "trade_date": compact(item["session"]),
                "up_limit": item["upper"],
                "down_limit": item["lower"],
            }
            for item in fixture_canonical["price_limits"]
        ],
        "industry_classification": [],
        "industry_membership": [
            {
                "ts_code": code_by_instrument[item["instrument_id"]],
                "in_date": compact(item["active_from"]),
                "out_date": "",
                "l1_code": item["sw2021_l1"],
                "l2_code": item["sw2021_l2"],
                "l3_code": item["sw2021_l3"],
            }
            for item in fixture_source["industry_membership"]
        ],
    }

    invalid_snapshot = {**snapshot, "daily": [dict(row) for row in snapshot["daily"]]}
    invalid_snapshot["daily"][0]["open"] = "NaN"
    with pytest.raises(TushareSourceError) as invalid_decimal:
        normalize_tushare_snapshot(invalid_snapshot)
    assert invalid_decimal.value.reason_code == "INVALID_DECIMAL"

    invalid_range_snapshot = {
        **snapshot,
        "daily": [dict(row) for row in snapshot["daily"]],
    }
    invalid_range_snapshot["daily"][0]["high"] = "1"
    with pytest.raises(TushareSourceError) as invalid_range:
        normalize_tushare_snapshot(invalid_range_snapshot)
    assert invalid_range.value.reason_code == "INVALID_DAILY_BAR"

    full_state = next(
        state
        for state in fixture_canonical["trading_states"]
        if state["state"] == "full_session_suspension"
    )
    contradictory_snapshot = {
        **snapshot,
        "daily": [
            *snapshot["daily"],
            {
                **snapshot["daily"][0],
                "ts_code": code_by_instrument[full_state["instrument_id"]],
                "trade_date": compact(full_state["session"]),
            },
        ],
    }
    with pytest.raises(TushareSourceError) as contradictory:
        normalize_tushare_snapshot(contradictory_snapshot)
    assert contradictory.value.reason_code == "CONTRADICTORY_SUSPENSION_EVIDENCE"

    partial = next(
        item
        for item in snapshot["suspensions"]
        if item["suspend_timing"] == "09:30-10:30"
    )
    ambiguous_snapshot = {
        **snapshot,
        "suspensions": [
            *snapshot["suspensions"],
            {**partial, "suspend_timing": "13:00-15:00", "suspend_type": "T"},
        ],
    }
    with pytest.raises(TushareSourceError) as ambiguous:
        normalize_tushare_snapshot(ambiguous_snapshot)
    assert ambiguous.value.reason_code == "AMBIGUOUS_SUSPENSION_EVIDENCE"

    retained_source, canonical = normalize_tushare_snapshot(snapshot)
    assert retained_source["source"] == "tushare"
    assert len(canonical["research_calendar"]) == 756
    assert len(canonical["instruments"]) == 35
    assert {
        item["anchor_session"] for item in canonical["adjustment_anchors"]
    } == {canonical["research_calendar"][0]}
    assert {
        item["state"] for item in canonical["trading_states"]
    } >= {
        "partial_opening_suspension",
        "after_open_suspension",
        "full_session_suspension",
    }

    metadata = MetadataStore(tmp_path / "live.sqlite3")
    metadata.initialize()
    publisher = DatasetPublisher(metadata, ImmutableObjectStore(tmp_path / "objects"))
    release, created = publisher.bootstrap_documents(
        "live-contract",
        source=retained_source,
        canonical=canonical,
        source_kind="source_tushare",
        source_schema="tushare-v1",
    )

    assert created is True
    assert release["predecessor_id"] is None
    assert release["session_count"] == 756
    assert {item["kind"] for item in release["objects"]} == {
        "source_tushare",
        "canonical_partition",
    }
    assert metadata.latest_dataset_release()["id"] == release["id"]


def test_live_increment_fetch_shape_publishes_only_the_new_source_slice(
    tmp_path: Path,
) -> None:
    fixture_source, prior = build_fixture()
    new_session = "2026-07-30"
    new_daily: list[dict[str, str]] = []
    new_adjustments: list[dict[str, str]] = []
    new_limits: list[dict[str, str]] = []
    anchors = {
        item["instrument_id"]: item["anchor_factor"]
        for item in prior["adjustment_anchors"]
    }
    factor = adjustment_factor(len(prior["research_calendar"]))
    for index, instrument in enumerate(fixture_source["instruments"]):
        source_row, _ = price_rows(
            session=new_session,
            session_index=len(prior["research_calendar"]),
            instrument=instrument,
            instrument_index=index,
            factor=factor,
            anchor_factor=Decimal(anchors[instrument["instrument_id"]]),
            state="normal",
        )
        new_daily.append({**source_row, "trade_date": compact(new_session)})
        new_adjustments.append(
            {
                "ts_code": instrument["ts_code"],
                "trade_date": compact(new_session),
                "adj_factor": decimal_string(factor, 6),
            }
        )
        new_limits.append(
            {
                "ts_code": instrument["ts_code"],
                "trade_date": compact(new_session),
                "up_limit": decimal_string(Decimal(source_row["pre_close"]) * Decimal("1.10"), 4),
                "down_limit": decimal_string(
                    Decimal(source_row["pre_close"]) * Decimal("0.90"),
                    4,
                ),
            }
        )
    snapshot = {
        "calendar_sse": [{"cal_date": compact(new_session), "is_open": "1"}],
        "calendar_szse": [{"cal_date": compact(new_session), "is_open": "1"}],
        "stock_basic": [
            {
                "ts_code": item["ts_code"],
                "exchange": item["exchange"],
                "market": "创业板" if item["board"] == "chinext" else "主板",
                "list_date": compact(item["listed_from"]),
                "delist_date": "",
            }
            for item in fixture_source["instruments"]
        ],
        "anchor_daily": [],
        "anchor_adjustments": [],
        "daily": new_daily,
        "adjustments": new_adjustments,
        "suspensions": [],
        "st": [],
        "price_limits": new_limits,
        "industry_membership": [
            {
                "ts_code": item["instrument_id"].removeprefix("equity:"),
                "in_date": compact(item["active_from"]),
                "out_date": "",
                "l1_code": item["sw2021_l1"],
                "l2_code": item["sw2021_l2"],
                "l3_code": item["sw2021_l3"],
            }
            for item in fixture_source["industry_membership"]
        ],
    }
    source_delta, canonical_delta = normalize_tushare_increment(snapshot, prior)
    assert len(source_delta["responses"]["daily"]) == len(prior["instruments"])
    assert canonical_delta["research_calendar_append"] == [new_session]

    historical_reference_change = {
        **snapshot,
        "stock_basic": [dict(row) for row in snapshot["stock_basic"]],
    }
    historical_reference_change["stock_basic"][0]["list_date"] = "20200101"
    with pytest.raises(TushareSourceError) as reference_change:
        normalize_tushare_increment(historical_reference_change, prior)
    assert (
        reference_change.value.reason_code
        == "HISTORICAL_INSTRUMENT_CORRECTION_REQUIRES_REVIEW"
    )

    historical_industry_change = {
        **snapshot,
        "industry_membership": [
            dict(row) for row in snapshot["industry_membership"]
        ],
    }
    historical_industry_change["industry_membership"][0]["l1_code"] = "CHANGED"
    with pytest.raises(TushareSourceError) as industry_change:
        normalize_tushare_increment(historical_industry_change, prior)
    assert (
        industry_change.value.reason_code
        == "HISTORICAL_INDUSTRY_CORRECTION_REQUIRES_REVIEW"
    )

    metadata = MetadataStore(tmp_path / "increment.sqlite3")
    metadata.initialize()
    publisher = DatasetPublisher(metadata, ImmutableObjectStore(tmp_path / "increment-objects"))
    root, _ = publisher.bootstrap_documents(
        "live-root",
        source=fixture_source,
        canonical=prior,
        source_kind="source_tushare",
        source_schema="tushare-v1",
    )
    release, created = publisher.publish_increment_documents(
        "live-daily",
        source=source_delta,
        canonical_delta=canonical_delta,
        source_schema="tushare-v1",
    )
    assert created is True
    assert release["predecessor_id"] == root["id"]
    assert release["session_count"] == 757
    assert publisher.materialize_canonical(release)["research_calendar"][-1] == new_session


def compact(value: str) -> str:
    return value.replace("-", "")
