import pytest
from pydantic import ValidationError

from thesistrace.research_agent.models import ListResearchRunsInput


def test_agent_query_accepts_native_metric_conditions_and_comparison_scope():
    query = ListResearchRunsInput.model_validate({
        "research_kind": "strategy_backtest", "status": "succeeded",
        "search": "  低波动  ", "universe": "top3000",
        "research_period": {"start_date": "2020-01-01", "end_date": "2025-12-31"},
        "metric_filters": [
            {"metric": "sharpe", "operator": "gte", "value": 1},
            {"metric": "maximum_drawdown", "operator": "lte", "value": 0.2},
        ],
        "sort_by": "sharpe", "sort_direction": "descending", "limit": 10,
    })
    assert query.search == "低波动"
    assert query.metric_filters[1].value == 0.2
    assert query.model_dump(mode="json")["research_period"] == {
        "start_date": "2020-01-01", "end_date": "2025-12-31",
    }


@pytest.mark.parametrize("fields", [
    {"sort_by": "sharpe"},
    {"research_kind": "factor_evaluation", "sort_by": "sharpe"},
    {"research_kind": "strategy_backtest", "metric_filters": [
        {"metric": "five_session_rank_ic", "operator": "gt", "value": 0}]},
    {"research_period": {"start_date": "2026-10-14", "end_date": "2026-10-13"}},
    {"research_kind": "strategy_backtest", "metric_filters": [
        {"metric": "sharpe", "operator": "gte", "value": True}]},
])
def test_agent_query_rejects_ambiguous_or_invalid_conditions(fields):
    with pytest.raises(ValidationError):
        ListResearchRunsInput.model_validate(fields)
