from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from thesistrace.data import bootstrap_collection_plan


def test_bootstrap_plan_uses_one_natural_year_and_completed_market_day() -> None:
    shanghai = ZoneInfo("Asia/Shanghai")

    after_close = bootstrap_collection_plan(datetime(2026, 8, 3, 18, tzinfo=shanghai))
    before_close = bootstrap_collection_plan(datetime(2026, 8, 3, 15, 59, tzinfo=shanghai))

    assert after_close.start_date.isoformat() == "2025-08-03"
    assert after_close.completed_through_date.isoformat() == "2026-08-03"
    assert before_close.start_date.isoformat() == "2025-08-03"
    assert before_close.completed_through_date.isoformat() == "2026-08-02"


def test_bootstrap_plan_handles_leap_day_and_requires_timezone() -> None:
    shanghai = ZoneInfo("Asia/Shanghai")
    plan = bootstrap_collection_plan(datetime(2028, 2, 29, 18, tzinfo=shanghai))
    assert plan.start_date.isoformat() == "2027-02-28"

    with pytest.raises(ValueError, match="timezone"):
        bootstrap_collection_plan(datetime(2026, 8, 3, 18))


def test_bootstrap_plan_accepts_an_explicit_start_date() -> None:
    shanghai = ZoneInfo("Asia/Shanghai")

    plan = bootstrap_collection_plan(
        datetime(2026, 8, 3, 18, tzinfo=shanghai),
        start_date=date(2026, 7, 3),
    )

    assert plan.start_date.isoformat() == "2026-07-03"
    assert plan.completed_through_date.isoformat() == "2026-08-03"


def test_bootstrap_plan_rejects_a_start_date_after_the_completed_day() -> None:
    shanghai = ZoneInfo("Asia/Shanghai")

    with pytest.raises(ValueError, match="start date"):
        bootstrap_collection_plan(
            datetime(2026, 8, 3, 15, 59, tzinfo=shanghai),
            start_date=date(2026, 8, 3),
        )
