from collections.abc import Mapping
from datetime import date
from pathlib import Path

import httpx
import pytest

from thesistrace.adapters.tushare_data import TushareDataSource, _materialize_increment
from thesistrace.adapters.tushare_provider import TushareAdapter, TushareSourceError
from thesistrace.data import CollectionPlan, DataSourceError
from thesistrace.fixture import build_fixture


class RecordingTransport:
    def __init__(self, denied_api: str | None = None) -> None:
        self.denied_api = denied_api
        self.payloads: list[dict[str, object]] = []

    def post(self, payload: Mapping[str, object]) -> dict[str, object]:
        copied = dict(payload)
        self.payloads.append(copied)
        if payload["api_name"] == self.denied_api:
            return {"code": 2002, "msg": "permission denied", "data": None}
        fields = str(payload["fields"]).split(",")
        return {
            "code": 0,
            "msg": "",
            "data": {
                "fields": fields,
                "items": [[field for field in fields]],
            },
        }


class RecordedProvider:
    def __init__(self) -> None:
        self.bootstrap_dates: list[date] = []
        self.incremental_calls: list[tuple[str, set[str], date]] = []

    def collect_bootstrap_snapshot(
        self, as_of: date
    ) -> dict[str, list[dict[str, object]]]:
        self.bootstrap_dates.append(as_of)
        return {"recorded": []}

    def collect_incremental_snapshot(
        self,
        *,
        last_session: str,
        known_ts_codes: set[str],
        as_of: date,
    ) -> dict[str, list[dict[str, object]]]:
        self.incremental_calls.append((last_session, known_ts_codes, as_of))
        return {"recorded": []}


def test_tushare_bootstrap_returns_the_canonical_source_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = RecordedProvider()
    _source, canonical = build_fixture()
    monkeypatch.setattr(
        "thesistrace.adapters.tushare_data.normalize_tushare_snapshot",
        lambda _snapshot: (
            {"source": "tushare", "source_contract_version": "tushare-v1"},
            canonical,
        ),
    )

    batch = TushareDataSource(
        provider=provider,
        clock=lambda: date(2026, 8, 3),
    ).collect(CollectionPlan.bootstrap())

    assert provider.bootstrap_dates == [date(2026, 8, 3)]
    assert batch.source_name == "tushare"
    assert batch.collection_kind == "bootstrap"
    assert batch.canonical["schema_version"] == "canonical-eod-v1"
    assert batch.covered_session_range == (
        canonical["research_calendar"][0],
        canonical["research_calendar"][-1],
    )


def test_tushare_increment_uses_only_frontier_and_previous_canonical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = RecordedProvider()
    _source, previous = build_fixture()
    frontier = str(previous["research_calendar"][-1])
    appended = "2028-11-27"
    monkeypatch.setattr(
        "thesistrace.adapters.tushare_data.normalize_tushare_increment",
        lambda _snapshot, _previous: (
            {"source": "tushare", "source_contract_version": "tushare-v1"},
            {
                "research_calendar_append": [appended],
                "instruments_replace": previous["instruments"],
                "prices_append": [],
                "trading_states_append": [],
                "price_limits_append": [],
                "base_pool_append": [],
                "adjustment_anchors_append": [],
                "st_designations_append": [],
                "liquidity_universes_append": {},
                "liquidity_universes_replace": {},
                "industry_membership_replace": previous["industry_membership"],
                "price_corrections": [],
            },
        ),
    )

    batch = TushareDataSource(
        provider=provider,
        clock=lambda: date(2026, 8, 4),
    ).collect(CollectionPlan.incremental(frontier, previous))

    known_codes = {
        str(item["ts_code"])
        for item in previous["instruments"]
        if isinstance(item, dict)
    }
    assert provider.incremental_calls == [
        (frontier, known_codes, date(2026, 8, 4))
    ]
    assert batch.canonical["research_calendar"] == [
        *previous["research_calendar"],
        appended,
    ]
    assert batch.covered_session_range == (
        previous["research_calendar"][0],
        appended,
    )


@pytest.mark.parametrize(
    ("reason_code", "category"),
    (
        ("TOKEN_MISSING", "authorization"),
        ("MISSING_PERMISSION", "authorization"),
        ("UPSTREAM_UNAVAILABLE", "unavailable"),
        ("INVALID_RESPONSE", "invalid_source_data"),
        ("INCOMPLETE_REQUIRED_MARKET_FACTS", "invalid_source_data"),
    ),
)
def test_tushare_maps_provider_failures_to_data_source_categories(
    reason_code: str,
    category: str,
) -> None:
    class FailingProvider(RecordedProvider):
        def collect_bootstrap_snapshot(
            self, as_of: date
        ) -> dict[str, list[dict[str, object]]]:
            raise TushareSourceError(reason_code, source_code=None)

    with pytest.raises(DataSourceError) as failure:
        TushareDataSource(provider=FailingProvider()).collect(
            CollectionPlan.bootstrap()
        )

    assert failure.value.category == category
    assert failure.value.detail_code == reason_code


def test_tushare_increment_requires_previous_canonical() -> None:
    with pytest.raises(DataSourceError) as failure:
        TushareDataSource(provider=RecordedProvider()).collect(
            CollectionPlan.incremental("2026-08-03")
        )

    assert failure.value.category == "invalid_source_data"
    assert failure.value.detail_code == "PREVIOUS_CANONICAL_REQUIRED"


def test_tushare_rejects_malformed_provider_snapshots_as_source_data() -> None:
    with pytest.raises(DataSourceError) as failure:
        TushareDataSource(provider=RecordedProvider()).collect(
            CollectionPlan.bootstrap()
        )

    assert failure.value.category == "invalid_source_data"
    assert failure.value.detail_code == "MALFORMED_PROVIDER_PAYLOAD"


def test_tushare_rejects_responses_missing_requested_fields() -> None:
    class MissingFieldTransport:
        def post(self, payload: dict[str, object]) -> dict[str, object]:
            return {
                "code": 0,
                "msg": "",
                "data": {"fields": ["ts_code"], "items": [["600000.SH"]]},
            }

    provider = TushareAdapter(
        token="recorded-token",
        transport=MissingFieldTransport(),
        throttle_seconds=0,
    )

    with pytest.raises(TushareSourceError) as failure:
        provider.query(
            "daily",
            params={},
            fields=("ts_code", "trade_date"),
        )

    assert failure.value.reason_code == "INVALID_RESPONSE"


def test_tushare_provider_preflight_checks_every_contract_without_exposing_token() -> None:
    transport = RecordingTransport()
    provider = TushareAdapter(
        token="deployment-secret-token",
        transport=transport,
        throttle_seconds=0,
    )

    result = provider.preflight()

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
    assert "deployment-secret-token" not in repr(result)
    assert all(payload["token"] == "deployment-secret-token" for payload in transport.payloads)


def test_tushare_provider_names_the_denied_contract() -> None:
    provider = TushareAdapter(
        token="secret",
        transport=RecordingTransport(denied_api="stock_st"),
        throttle_seconds=0,
    )

    with pytest.raises(TushareSourceError) as failure:
        provider.preflight()

    assert failure.value.diagnostic() == {
        "reason_code": "MISSING_PERMISSION",
        "source_code": 2002,
        "contract": "st",
    }


def test_tushare_provider_paginates_deduplicates_and_sorts() -> None:
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
    provider = TushareAdapter(
        token="secret",
        transport=transport,
        page_size=2,
        throttle_seconds=0,
    )

    rows = provider.query_paginated(
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


def test_tushare_provider_searches_later_windows_for_adjustment_anchor() -> None:
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

    provider = TushareAdapter(
        token="secret",
        transport=DelayedAnchorTransport(),
        throttle_seconds=0,
    )

    daily, adjustments = provider._collect_adjustment_anchors(
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


def test_tushare_provider_retries_transient_http_statuses() -> None:
    class UnavailableTransport:
        def __init__(self) -> None:
            self.calls = 0

        def post(self, payload: Mapping[str, object]) -> dict[str, object]:
            del payload
            self.calls += 1
            request = httpx.Request("POST", "https://api.tushare.pro")
            response = httpx.Response(503, request=request)
            raise httpx.HTTPStatusError(
                "unavailable",
                request=request,
                response=response,
            )

    transport = UnavailableTransport()
    provider = TushareAdapter(
        token="secret",
        transport=transport,
        throttle_seconds=0,
        max_attempts=3,
    )

    with pytest.raises(TushareSourceError) as failure:
        provider.query("daily", params={}, fields=("ts_code",))

    assert failure.value.diagnostic() == {
        "reason_code": "UPSTREAM_UNAVAILABLE",
        "source_code": 503,
    }
    assert transport.calls == 3


def test_tushare_materializes_price_corrections_by_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = RecordedProvider()
    _source, previous = build_fixture()
    frontier = str(previous["research_calendar"][-1])
    target = previous["prices"][0]
    monkeypatch.setattr(
        "thesistrace.adapters.tushare_data.normalize_tushare_increment",
        lambda _snapshot, _previous: (
            {"source": "tushare"},
            {
                "research_calendar_append": [],
                "instruments_replace": previous["instruments"],
                "prices_append": [],
                "trading_states_append": [],
                "price_limits_append": [],
                "base_pool_append": [],
                "adjustment_anchors_append": [],
                "st_designations_append": [],
                "liquidity_universes_append": {},
                "liquidity_universes_replace": {},
                "industry_membership_replace": previous["industry_membership"],
                "price_corrections": [
                    {
                        "session": target["session"],
                        "instrument_id": target["instrument_id"],
                        "field": "close_raw",
                        "value": "99.0000",
                    }
                ],
            },
        ),
    )

    batch = TushareDataSource(provider=provider).collect(
        CollectionPlan.incremental(frontier, previous)
    )
    corrected = batch.canonical["prices"][0]

    assert corrected["close_raw"] == "99.0000"
    assert "field" not in corrected
    assert "value" not in corrected


@pytest.mark.parametrize(
    "field",
    ("provider_private_field", "close_adj", "session"),
)
def test_tushare_rejects_non_source_price_correction_fields(field: str) -> None:
    _source, previous = build_fixture()
    target = previous["prices"][0]
    delta = {
        "research_calendar_append": [],
        "instruments_replace": previous["instruments"],
        "prices_append": [],
        "trading_states_append": [],
        "price_limits_append": [],
        "base_pool_append": [],
        "adjustment_anchors_append": [],
        "st_designations_append": [],
        "liquidity_universes_append": {},
        "liquidity_universes_replace": {},
        "industry_membership_replace": previous["industry_membership"],
        "price_corrections": [
            {
                "session": target["session"],
                "instrument_id": target["instrument_id"],
                "field": field,
                "value": "123",
            }
        ],
    }

    with pytest.raises(DataSourceError) as failure:
        _materialize_increment(previous, delta)

    assert failure.value.category == "invalid_source_data"
    assert failure.value.detail_code == "INVALID_CANONICAL_INCREMENT"


def test_tushare_adapter_has_no_product_or_infrastructure_knowledge() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "thesistrace"
        / "adapters"
        / "tushare_data.py"
    ).read_text()
    for forbidden in (
        "release_id",
        "postgres",
        "publication",
        "s3",
        "researchrun",
        "research_run",
        "dailytrack",
        "daily_track",
    ):
        assert forbidden not in source.lower()


def test_tushare_provider_does_not_own_canonical_calendar_or_fixture_rules() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "thesistrace"
        / "adapters"
        / "tushare_provider.py"
    ).read_text()
    collector = source.split("def collect_bootstrap_snapshot", maxsplit=1)[1].split(
        "def collect_incremental_snapshot", maxsplit=1
    )[0]

    assert "from thesistrace.fixture" not in source
    assert "len(common)" not in collector
    assert "common[-756:]" not in collector
