import pytest
from pydantic import TypeAdapter, ValidationError

from thesistrace.research_run.models import ResearchRunResultSectionInput


def test_daily_factor_query_requires_horizon_and_valid_signal_date_scope():
    adapter = TypeAdapter(ResearchRunResultSectionInput)
    base = {"run_id": "run-factor", "section": "factor_observations", "horizon": 5}
    query = adapter.validate_python({**base, "start_session": "2026-01-02", "limit": 50})
    assert query.horizon == 5
    assert query.start_session == "2026-01-02"
    for invalid in (
        {"horizon": True},
        {"horizon": 2},
        {"limit": 51},
        {"start_session": "2026-02-30"},
        {"start_session": "2026-02-01", "end_session": "2026-01-01"},
    ):
        with pytest.raises(ValidationError):
            adapter.validate_python({**base, **invalid})


def test_daily_factor_section_is_advertised_only_for_completed_factor_runs():
    from thesistrace.research_run.models import research_run_result_sections

    assert "factor_observations" in research_run_result_sections("succeeded", "factor_evaluation")
    assert "factor_observations" not in research_run_result_sections("running", "factor_evaluation")
    assert "factor_observations" not in research_run_result_sections(
        "succeeded", "strategy_backtest"
    )


def test_period_section_requires_explicit_bucket_and_rejects_daily_date_filters():
    from thesistrace.research_run.models import research_run_result_sections

    adapter = TypeAdapter(ResearchRunResultSectionInput)
    base = {
        "run_id": "run-factor",
        "section": "factor_periods",
        "horizon": 5,
        "granularity": "month",
    }
    assert adapter.validate_python(base).granularity == "month"
    assert "factor_periods" in research_run_result_sections("succeeded", "factor_evaluation")
    for invalid in (
        {"granularity": "week"},
        {"horizon": True},
        {"limit": 51},
        {"start_session": "2026-01-01"},
    ):
        with pytest.raises(ValidationError):
            adapter.validate_python({**base, **invalid})
