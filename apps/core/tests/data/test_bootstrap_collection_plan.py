from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from thesistrace.data import bootstrap_collection_plan


def test_bootstrap_plan_uses_one_natural_year_and_completed_market_day() -> None:
    shanghai = ZoneInfo("Asia/Shanghai")

    after_close = bootstrap_collection_plan(datetime(2026, 8, 3, 18, tzinfo=shanghai),
        collection_key="test-collection")
    before_close = bootstrap_collection_plan(datetime(2026, 8, 3, 15, 59, tzinfo=shanghai),
        collection_key="test-collection")

    assert after_close.start_date.isoformat() == "2025-08-03"
    assert after_close.completed_through_date.isoformat() == "2026-08-03"
    assert before_close.start_date.isoformat() == "2025-08-03"
    assert before_close.completed_through_date.isoformat() == "2026-08-02"


def test_bootstrap_plan_handles_leap_day_and_requires_timezone() -> None:
    shanghai = ZoneInfo("Asia/Shanghai")
    plan = bootstrap_collection_plan(datetime(2028, 2, 29, 18, tzinfo=shanghai),
        collection_key="test-collection")
    assert plan.start_date.isoformat() == "2027-02-28"

    with pytest.raises(ValueError, match="timezone"):
        bootstrap_collection_plan(datetime(2026, 8, 3, 18), collection_key="test-collection")


def test_bootstrap_plan_accepts_an_explicit_start_date() -> None:
    shanghai = ZoneInfo("Asia/Shanghai")

    plan = bootstrap_collection_plan(
        datetime(2026, 8, 3, 18, tzinfo=shanghai),
        start_date=date(2026, 7, 3),
     collection_key="test-collection")

    assert plan.start_date.isoformat() == "2026-07-03"
    assert plan.completed_through_date.isoformat() == "2026-08-03"


def test_bootstrap_plan_rejects_a_start_date_after_the_completed_day() -> None:
    shanghai = ZoneInfo("Asia/Shanghai")

    with pytest.raises(ValueError, match="start date"):
        bootstrap_collection_plan(
            datetime(2026, 8, 3, 15, 59, tzinfo=shanghai),
            start_date=date(2026, 8, 3),
         collection_key="test-collection")


def test_operation_identity_is_preserved_independently_of_the_date_window() -> None:
    from thesistrace.data.source import refresh_collection_plan

    as_of = datetime(2026, 8, 3, 18, tzinfo=ZoneInfo('Asia/Shanghai'))
    first = bootstrap_collection_plan(as_of, collection_key='bootstrap:first')
    second = bootstrap_collection_plan(as_of, collection_key='bootstrap:second')
    assert (first.start_date, first.completed_through_date) == (
        second.start_date, second.completed_through_date,
    )
    assert first.collection_key == 'bootstrap:first'
    assert second.collection_key == 'bootstrap:second'
    refreshed = refresh_collection_plan(
        as_of, {'research_calendar': ['2026-07-31']}, collection_key='refresh:next',
    )
    assert refreshed.collection_key == 'refresh:next'


@pytest.mark.parametrize('key', ['', ' ', ' operation '])
def test_collection_rejects_empty_or_noncanonical_operation_identity(key: str) -> None:
    with pytest.raises(ValueError, match='Collection key'):
        bootstrap_collection_plan(
            datetime(2026, 8, 3, 18, tzinfo=ZoneInfo('Asia/Shanghai')), collection_key=key,
        )
