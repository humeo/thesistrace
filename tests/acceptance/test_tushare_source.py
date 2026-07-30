from collections.abc import Mapping
from pathlib import Path

from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.fixture import build_fixture
from thesistrace.objects import ImmutableObjectStore
from thesistrace.storage import MetadataStore
from thesistrace.tushare_source import TushareAdapter, normalize_tushare_snapshot


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
        "suspensions": [
            {
                "ts_code": code_by_instrument[state["instrument_id"]],
                "trade_date": compact(state["session"]),
                "suspend_timing": "全天",
                "suspend_type": "S",
            }
            for state in fixture_canonical["trading_states"]
            if state["state"] == "full_session_suspension"
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

    retained_source, canonical = normalize_tushare_snapshot(snapshot)
    assert retained_source["source"] == "tushare"
    assert len(canonical["research_calendar"]) == 756
    assert len(canonical["instruments"]) == 35

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
        "canonical_fixture",
    }
    assert metadata.latest_dataset_release()["id"] == release["id"]


def compact(value: str) -> str:
    return value.replace("-", "")
