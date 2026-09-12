import math

import pytest

from thesistrace.research_kernel.factor import factor_values


def _day(session, exit_session, *, count, reverse=False):
    labels = [index / 100 for index in range(count)]
    metrics = factor_values(list(range(count)), list(reversed(labels)) if reverse else labels)
    return {
        **metrics,
        "horizon": 1,
        "session": session,
        "label_entry_session": {
            "2025-12-30": "2025-12-31",
            "2025-12-31": "2026-01-02",
            "2026-01-02": "2026-01-05",
        }[session],
        "label_exit_session": exit_session,
        "label_status": "within_research_period",
        "alpha_candidate_count": count,
        "alpha_sample_count": count,
        "sample_count": count,
        "alpha_exclusions": {},
        "label_exclusions": {},
    }


def test_period_statistics_weight_days_equally_and_keep_cross_month_labels():
    from thesistrace.research_kernel.factor_periods import FactorPeriodAccumulator

    days = [
        _day("2025-12-30", "2026-01-02", count=30),
        _day("2025-12-31", "2026-01-05", count=60, reverse=True),
        _day("2026-01-02", "2026-01-06", count=30),
    ]
    accumulator = FactorPeriodAccumulator()
    accumulator.add(days[:1])
    accumulator.add(days[1:])
    periods = accumulator.finish()
    december = next(row for row in periods if row["period"] == "2025-12")
    correlation = december["summary"]["rank_ic"]
    assert correlation["mean"] == pytest.approx(0)
    assert correlation["sample_deviation"] == pytest.approx(math.sqrt(2))
    assert correlation["icir"] == pytest.approx(0)
    assert correlation["valid_session_count"] == 2
    assert december["coverage"]["sample_count"] == 90
    assert december["coverage"]["label_evaluable_session_count"] == 2
    assert december["coverage"]["last_evaluable_signal_session"] == "2025-12-31"
    full = next(row for row in periods if row["granularity"] == "all")
    assert full["summary"]["rank_ic"]["mean"] == pytest.approx(1 / 3)
    assert len(periods) == 5  # all, two years, two months
    uninterrupted = FactorPeriodAccumulator()
    uninterrupted.add(days)
    assert periods == uninterrupted.finish()
    with pytest.raises(ValueError, match="ordered"):
        accumulator.add(days[:1])


def test_censored_period_has_coverage_but_no_fabricated_statistics(accepted_calculation_case):
    from thesistrace.research_kernel.factor_periods import FactorPeriodAccumulator

    tail = accepted_calculation_case["factor_evaluation"]["horizons"]["20"]["daily"][-1]
    accumulator = FactorPeriodAccumulator()
    accumulator.add([tail])
    full = next(row for row in accumulator.finish() if row["granularity"] == "all")
    assert full["summary"]["ic"]["mean"] is None
    assert full["coverage"]["right_censored_session_count"] == 1
    assert full["coverage"]["label_evaluable_session_count"] == 0
    assert full["coverage"]["first_evaluable_signal_session"] is None
    assert full["coverage"]["sample_count"] == 0


def test_period_schema_rejects_inconsistent_counts_and_signal_bucket():
    from thesistrace.research_kernel.factor_periods import FactorPeriodAccumulator
    from thesistrace.research_run.result_schema import FactorPeriodStatistic

    accumulator = FactorPeriodAccumulator()
    accumulator.add([_day("2025-12-30", "2026-01-02", count=30)])
    month = next(row for row in accumulator.finish() if row["granularity"] == "month")
    FactorPeriodStatistic.model_validate(month)
    for invalid in (
        {**month, "period": "2026-01"},
        {**month, "coverage": {**month["coverage"], "sample_count": -1}},
        {**month, "coverage": {**month["coverage"], "right_censored_session_count": 1}},
    ):
        with pytest.raises(ValueError):
            FactorPeriodStatistic.model_validate(invalid)
