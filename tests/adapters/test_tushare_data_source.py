import copy
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from thesistrace.adapters.tushare_data import TushareDataSource, _materialize_increment
from thesistrace.adapters.tushare_provider import (
    TushareAdapter,
    TushareSourceError,
    normalize_tushare_increment,
    normalize_tushare_snapshot,
)
from thesistrace.data import BootstrapCollectionPlan, CollectionPlan, DataSourceError
from thesistrace.data.source import refresh_collection_plan
from thesistrace.data.validation import validate_release_batch
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


def normalizer_snapshot(session_keys: list[str]) -> dict[str, list[dict[str, object]]]:
    daily = [
        {
            "ts_code": "600000.SH",
            "trade_date": session,
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
        for session in session_keys
    ]
    return {
        "calendar_sse": [
            {"exchange": "SSE", "cal_date": session, "is_open": "1"} for session in session_keys
        ],
        "calendar_szse": [
            {"exchange": "SZSE", "cal_date": session, "is_open": "1"} for session in session_keys
        ],
        "stock_basic": [
            {
                "ts_code": "600000.SH",
                "exchange": "SSE",
                "market": "主板",
                "list_date": "20220101",
                "delist_date": "",
            }
        ],
        "anchor_daily": [dict(daily[0])],
        "anchor_adjustments": [
            {
                "ts_code": "600000.SH",
                "trade_date": session_keys[0],
                "adj_factor": "1",
            }
        ],
        "daily": daily,
        "adjustments": [
            {
                "ts_code": "600000.SH",
                "trade_date": session,
                "adj_factor": "1",
            }
            for session in session_keys
        ],
        "suspensions": [],
        "st": [],
        "price_limits": [
            {
                "ts_code": "600000.SH",
                "trade_date": session,
                "up_limit": "11",
                "down_limit": "9",
            }
            for session in session_keys
        ],
        "industry_membership": [
            {
                "ts_code": "600000.SH",
                "in_date": "20220101",
                "out_date": "",
                "l1_code": "801010",
                "l2_code": "801011",
                "l3_code": "850111",
            }
        ],
    }


def normalizer_bootstrap_sessions() -> list[str]:
    return ["20260803", "20260804", "20260805"]


class RecordedProvider:
    def __init__(self) -> None:
        self.bootstrap_windows: list[tuple[date, date]] = []
        self.incremental_calls: list[tuple[str, set[str], date]] = []

    def collect_bootstrap_snapshot(
        self,
        *,
        start_date: date,
        completed_through_date: date,
    ) -> dict[str, list[dict[str, object]]]:
        self.bootstrap_windows.append((start_date, completed_through_date))
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

    start = date.fromisoformat(str(canonical["research_calendar"][0]))
    end = date.fromisoformat(str(canonical["research_calendar"][-1]))
    batch = TushareDataSource(provider=provider).collect_bootstrap(
        BootstrapCollectionPlan(
            as_of=datetime(2026, 8, 3, 18, tzinfo=UTC),
            start_date=start,
            completed_through_date=end,
        )
    )

    assert provider.bootstrap_windows == [(start, end)]
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
        str(item["ts_code"]) for item in previous["instruments"] if isinstance(item, dict)
    }
    assert provider.incremental_calls == [(frontier, known_codes, date(2026, 8, 4))]
    assert batch.canonical["research_calendar"] == [
        *previous["research_calendar"],
        appended,
    ]
    assert batch.covered_session_range == (
        previous["research_calendar"][0],
        appended,
    )


def test_tushare_refresh_merges_exact_overlap_and_recomputes_derived_data() -> None:
    sessions: list[str] = []
    cursor = date(2026, 7, 1)
    while len(sessions) < 22:
        if cursor.weekday() < 5:
            sessions.append(cursor.strftime("%Y%m%d"))
        cursor += timedelta(days=1)
    bootstrap_snapshot = normalizer_snapshot(sessions[:21])
    preserved_st_session = sessions[6]
    bootstrap_snapshot["st"] = [
        {
            "ts_code": "600000.SH",
            "trade_date": preserved_st_session,
            "name": "ST浦发",
            "type": "S",
            "type_name": "特别处理",
        }
    ]
    _source, previous = normalize_tushare_snapshot(bootstrap_snapshot)

    refresh_snapshot = normalizer_snapshot(sessions[1:])
    ordinary_missing = sessions[1]
    suspension_session = sessions[2]
    factor_session = sessions[3]
    turnover_session = sessions[4]
    for table in ("daily", "adjustments", "price_limits"):
        refresh_snapshot[table] = [
            row for row in refresh_snapshot[table] if row["trade_date"] != ordinary_missing
        ]
    for table in ("calendar_sse", "calendar_szse"):
        refresh_snapshot[table] = [
            row for row in refresh_snapshot[table] if row["cal_date"] != ordinary_missing
        ]
    refresh_snapshot["daily"] = [
        row for row in refresh_snapshot["daily"] if row["trade_date"] != suspension_session
    ]
    refresh_snapshot["suspensions"] = [
        {
            "ts_code": "600000.SH",
            "trade_date": suspension_session,
            "suspend_timing": "全天",
            "suspend_type": "S",
        }
    ]
    next(row for row in refresh_snapshot["adjustments"] if row["trade_date"] == factor_session)[
        "adj_factor"
    ] = "2"
    next(row for row in refresh_snapshot["daily"] if row["trade_date"] == turnover_session)[
        "amount"
    ] = "9000"
    refresh_snapshot["st"] = []

    class RefreshProvider(RecordedProvider):
        def collect_incremental_snapshot(
            self,
            *,
            last_session: str,
            known_ts_codes: set[str],
            as_of: date,
        ) -> dict[str, list[dict[str, object]]]:
            self.incremental_calls.append((last_session, known_ts_codes, as_of))
            return copy.deepcopy(refresh_snapshot)

    provider = RefreshProvider()
    plan = refresh_collection_plan(datetime(2026, 7, 30, 18, tzinfo=UTC), previous)
    batch = TushareDataSource(provider=provider).collect(plan)

    assert provider.incremental_calls == [
        (
            f"{sessions[1][:4]}-{sessions[1][4:6]}-{sessions[1][6:]}",
            {"600000.SH"},
            date(2026, 7, 30),
        )
    ]
    assert batch.canonical["research_calendar"] == [
        f"{value[:4]}-{value[4:6]}-{value[6:]}" for value in sessions
    ]
    instrument_id = "equity:600000.SH"
    prices = {(row["session"], row["instrument_id"]): row for row in batch.canonical["prices"]}
    previous_prices = {(row["session"], row["instrument_id"]): row for row in previous["prices"]}
    ordinary_position = (
        f"{ordinary_missing[:4]}-{ordinary_missing[4:6]}-{ordinary_missing[6:]}",
        instrument_id,
    )
    assert prices[ordinary_position] == previous_prices[ordinary_position]
    suspension_position = (
        f"{suspension_session[:4]}-{suspension_session[4:6]}-{suspension_session[6:]}",
        instrument_id,
    )
    assert suspension_position not in prices
    assert (
        next(
            row
            for row in batch.canonical["trading_states"]
            if (row["session"], row["instrument_id"]) == suspension_position
        )["state"]
        == "full_session_suspension"
    )
    factor_position = (
        f"{factor_session[:4]}-{factor_session[4:6]}-{factor_session[6:]}",
        instrument_id,
    )
    assert prices[factor_position]["adjustment_factor"] == "2.000000"
    assert prices[factor_position]["open_adj"] == "20.00000000"
    turnover_position = (
        f"{turnover_session[:4]}-{turnover_session[4:6]}-{turnover_session[6:]}",
        instrument_id,
    )
    assert prices[turnover_position]["turnover_cny"] == "9000000.00"
    assert any(
        row["trade_date"]
        == f"{preserved_st_session[:4]}-{preserved_st_session[4:6]}-{preserved_st_session[6:]}"
        for row in batch.canonical["st_designations"]
    )
    for rows in batch.canonical["liquidity_universes"].values():
        assert rows[-1]["session"] == batch.canonical["research_calendar"][-1]
        assert len(rows) == len(sessions)
    validate_release_batch(batch, predecessor_session=previous["research_calendar"][-1])


def test_tushare_refresh_supports_coverage_shorter_than_the_overlap_window() -> None:
    _source, previous = normalize_tushare_snapshot(normalizer_snapshot(["20260701"]))
    snapshot = normalizer_snapshot(["20260701", "20260702"])

    class ShortCoverageProvider(RecordedProvider):
        def collect_incremental_snapshot(
            self,
            *,
            last_session: str,
            known_ts_codes: set[str],
            as_of: date,
        ) -> dict[str, list[dict[str, object]]]:
            self.incremental_calls.append((last_session, known_ts_codes, as_of))
            return copy.deepcopy(snapshot)

    plan = refresh_collection_plan(datetime(2026, 7, 2, 18, tzinfo=UTC), previous)
    batch = TushareDataSource(provider=ShortCoverageProvider()).collect(plan)

    assert batch.canonical["research_calendar"] == ["2026-07-01", "2026-07-02"]
    assert len(batch.canonical["prices"]) == 2
    for rows in batch.canonical["liquidity_universes"].values():
        assert [row["instrument_ids"] for row in rows] == [
            ["equity:600000.SH"],
            ["equity:600000.SH"],
        ]
    validate_release_batch(batch, predecessor_session="2026-07-01")


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
            self,
            *,
            start_date: date,
            completed_through_date: date,
        ) -> dict[str, list[dict[str, object]]]:
            raise TushareSourceError(reason_code, source_code=None)

    with pytest.raises(DataSourceError) as failure:
        TushareDataSource(provider=FailingProvider()).collect_bootstrap(
            BootstrapCollectionPlan(
                as_of=datetime(2026, 8, 3, 18, tzinfo=UTC),
                start_date=date(2025, 8, 3),
                completed_through_date=date(2026, 8, 3),
            )
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
        TushareDataSource(provider=RecordedProvider()).collect_bootstrap(
            BootstrapCollectionPlan(
                as_of=datetime(2026, 8, 3, 18, tzinfo=UTC),
                start_date=date(2025, 8, 3),
                completed_through_date=date(2026, 8, 3),
            )
        )

    assert failure.value.category == "invalid_source_data"
    assert failure.value.detail_code == "MALFORMED_PROVIDER_PAYLOAD"


def test_tushare_normalizer_maps_a_complete_bootstrap_and_increment() -> None:
    sessions = normalizer_bootstrap_sessions()
    source, canonical = normalize_tushare_snapshot(normalizer_snapshot(sessions))

    assert source["source_contract_version"] == "tushare-v1"
    assert canonical["research_calendar"] == [
        f"{session[:4]}-{session[4:6]}-{session[6:]}" for session in sessions
    ]
    assert canonical["instruments"] == [
        {
            "instrument_id": "equity:600000.SH",
            "ts_code": "600000.SH",
            "asset_type": "ordinary_a_share",
            "exchange": "SSE",
            "board": "main",
            "listed_from": "2022-01-01",
            "listed_to": "",
        }
    ]
    assert len(canonical["prices"]) == len(sessions)
    assert canonical["prices"][0]["volume_shares"] == "10000"
    assert canonical["prices"][0]["turnover_cny"] == "1000000.00"

    next_session = (
        date.fromisoformat(canonical["research_calendar"][-1]) + timedelta(days=1)
    ).strftime("%Y%m%d")
    source_delta, canonical_delta = normalize_tushare_increment(
        normalizer_snapshot([next_session]),
        canonical,
    )

    assert source_delta["corrections"] == []
    assert canonical_delta["research_calendar_append"] == [
        f"{next_session[:4]}-{next_session[4:6]}-{next_session[6:]}"
    ]
    assert len(canonical_delta["prices_append"]) == 1
    assert canonical_delta["price_corrections"] == []


@pytest.mark.parametrize(
    ("field", "value", "reason_code"),
    (
        ("open", "NaN", "INVALID_DECIMAL"),
        ("low", "12", "INVALID_DAILY_BAR"),
    ),
)
def test_tushare_normalizer_rejects_invalid_market_values(
    field: str,
    value: str,
    reason_code: str,
) -> None:
    snapshot = normalizer_snapshot(normalizer_bootstrap_sessions())
    snapshot["daily"][0][field] = value

    with pytest.raises(TushareSourceError) as failure:
        normalize_tushare_snapshot(snapshot)

    assert failure.value.reason_code == reason_code


@pytest.mark.parametrize(
    ("suspend_timing", "reason_code"),
    (
        ("全天", "CONTRADICTORY_SUSPENSION_EVIDENCE"),
        ("无法识别", "AMBIGUOUS_SUSPENSION_EVIDENCE"),
    ),
)
def test_tushare_normalizer_rejects_invalid_suspension_evidence(
    suspend_timing: str,
    reason_code: str,
) -> None:
    sessions = normalizer_bootstrap_sessions()
    snapshot = normalizer_snapshot(sessions)
    snapshot["suspensions"] = [
        {
            "ts_code": "600000.SH",
            "trade_date": sessions[0],
            "suspend_timing": suspend_timing,
        }
    ]

    with pytest.raises(TushareSourceError) as failure:
        normalize_tushare_snapshot(snapshot)

    assert failure.value.reason_code == reason_code


def test_tushare_increment_rejects_historical_reference_changes() -> None:
    sessions = normalizer_bootstrap_sessions()
    _source, canonical = normalize_tushare_snapshot(normalizer_snapshot(sessions))
    next_session = (
        date.fromisoformat(canonical["research_calendar"][-1]) + timedelta(days=1)
    ).strftime("%Y%m%d")
    snapshot = normalizer_snapshot([next_session])

    instrument_change = copy.deepcopy(snapshot)
    instrument_change["stock_basic"][0]["list_date"] = "20210101"
    with pytest.raises(TushareSourceError) as instrument_failure:
        normalize_tushare_increment(instrument_change, canonical)
    assert (
        instrument_failure.value.reason_code == "HISTORICAL_INSTRUMENT_CORRECTION_REQUIRES_REVIEW"
    )

    industry_change = copy.deepcopy(snapshot)
    industry_change["industry_membership"][0]["l1_code"] = "CHANGED"
    with pytest.raises(TushareSourceError) as industry_failure:
        normalize_tushare_increment(industry_change, canonical)
    assert industry_failure.value.reason_code == "HISTORICAL_INDUSTRY_CORRECTION_REQUIRES_REVIEW"


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


def test_tushare_bootstrap_queries_one_year_and_stops_facts_at_latest_open_session() -> None:
    class WindowRecordingAdapter(TushareAdapter):
        def __init__(self) -> None:
            super().__init__(token="secret", transport=RecordingTransport(), throttle_seconds=0)
            self.calls: list[tuple[str, dict[str, object]]] = []

        def query_paginated(
            self,
            api_name: str,
            *,
            params: Mapping[str, object],
            fields: tuple[str, ...],
            primary_key: tuple[str, ...],
        ) -> list[dict[str, object]]:
            del fields, primary_key
            self.calls.append((api_name, dict(params)))
            if api_name == "trade_cal":
                exchange = str(params["exchange"])
                return [
                    {
                        "exchange": exchange,
                        "cal_date": "20260803",
                        "is_open": "1",
                        "pretrade_date": "20260731",
                    },
                    {
                        "exchange": exchange,
                        "cal_date": "20260804",
                        "is_open": "0",
                        "pretrade_date": "20260803",
                    },
                ]
            if api_name == "stock_basic":
                if params["list_status"] != "L":
                    return []
                return [
                    {
                        "ts_code": "600000.SH",
                        "exchange": "SSE",
                        "market": "主板",
                        "list_status": "L",
                        "list_date": "20220103",
                        "delist_date": "",
                    }
                ]
            if api_name == "daily":
                session = "20220103" if params.get("trade_date") else "20260803"
                return [
                    {
                        "ts_code": "600000.SH",
                        "trade_date": session,
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
                ]
            if api_name == "adj_factor":
                session = "20220103" if params.get("trade_date") else "20260803"
                return [{"ts_code": "600000.SH", "trade_date": session, "adj_factor": "1"}]
            if api_name == "stk_limit":
                return [
                    {
                        "ts_code": "600000.SH",
                        "trade_date": "20260803",
                        "pre_close": "10",
                        "up_limit": "11",
                        "down_limit": "9",
                    }
                ]
            if api_name == "index_member_all":
                return [
                    {
                        "l1_code": "801010",
                        "l2_code": "801011",
                        "l3_code": "850111",
                        "ts_code": "600000.SH",
                        "in_date": "20220103",
                        "out_date": "",
                    }
                ]
            return []

    provider = WindowRecordingAdapter()
    snapshot = provider.collect_bootstrap_snapshot(
        start_date=date(2025, 8, 4),
        completed_through_date=date(2026, 8, 4),
    )

    calendar_calls = [params for api, params in provider.calls if api == "trade_cal"]
    ranged_daily = next(
        params for api, params in provider.calls if api == "daily" and "start_date" in params
    )
    assert calendar_calls == [
        {"exchange": "SSE", "start_date": "20250804", "end_date": "20260804"},
        {"exchange": "SZSE", "start_date": "20250804", "end_date": "20260804"},
    ]
    assert ranged_daily == {"start_date": "20250804", "end_date": "20260803"}
    assert snapshot["daily"][0]["trade_date"] == "20260803"


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
        Path(__file__).resolve().parents[2] / "src" / "thesistrace" / "adapters" / "tushare_data.py"
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
