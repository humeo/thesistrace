from datetime import date
from pathlib import Path

import pytest

from thesistrace.adapters.tushare_data import TushareDataSource, _materialize_increment
from thesistrace.data import CollectionPlan, DataSourceError
from thesistrace.fixture import build_fixture
from thesistrace.tushare_source import TushareAdapter, TushareSourceError


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
        / "tushare_source.py"
    ).read_text()
    collector = source.split("def collect_bootstrap_snapshot", maxsplit=1)[1].split(
        "def collect_incremental_snapshot", maxsplit=1
    )[0]

    assert "from thesistrace.fixture" not in source
    assert "len(common)" not in collector
    assert "common[-756:]" not in collector
