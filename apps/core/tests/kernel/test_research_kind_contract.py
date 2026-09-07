from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from thesistrace.research_run.models import ResearchRunAdmissionCommand


def test_research_run_admission_is_discriminated_by_research_kind() -> None:
    adapter = TypeAdapter(ResearchRunAdmissionCommand)
    common = {
        "request_id": "research-kind-contract",
        "folder_id": "folder_default",
        "formula": "close",
        "start_date": "2026-08-03",
        "end_date": "2026-08-05",
        "universe": "top300",
        "neutralization": "none",
    }

    factor = adapter.validate_python(
        {
            **common,
            "research_kind": "factor_evaluation",
        }
    )
    strategy = adapter.validate_python(
        {
            **common,
            "research_kind": "strategy_backtest",
            "holdings_count": 10,
            "rebalance_every_sessions": 5,
        }
    )

    assert factor.research_kind == "factor_evaluation"
    assert set(factor.model_dump()) == {
        "request_id",
        "folder_id",
        "name",
        "formula",
        "hypothesis",
        "start_date",
        "end_date",
        "universe",
        "neutralization",
        "research_kind",
    }
    assert strategy.research_kind == "strategy_backtest"
    assert strategy.holdings_count == 10
    assert strategy.rebalance_every_sessions == 5

    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                **common,
                "research_kind": "factor_evaluation",
                "holdings_count": 10,
                "rebalance_every_sessions": 5,
            }
        )
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                **common,
                "research_kind": "strategy_backtest",
            }
        )
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                **common,
                "research_kind": "unknown",
            }
        )
