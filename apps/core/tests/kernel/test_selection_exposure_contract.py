import pytest
from pydantic import TypeAdapter, ValidationError

from thesistrace.research_run.models import ResearchRunAdmissionCommand


def strategy_command():
    return {
        "request_id": "selection-exposure-contract",
        "folder_id": "folder_default",
        "research_kind": "strategy_backtest",
        "formula": "close",
        "start_date": "2026-08-03",
        "end_date": "2026-08-05",
        "universe": "top300",
        "neutralization": "none",
        "initial_cash_cny": "100000",
        "holdings_count": 10,
        "selection_every_sessions": 5,
    }


def test_selection_schedule_has_one_current_public_name():
    adapter = TypeAdapter(ResearchRunAdmissionCommand)
    command = strategy_command()
    accepted = adapter.validate_python(command)
    assert accepted.selection_every_sessions == 5
    assert "rebalance_every_sessions" not in accepted.model_dump()
    with pytest.raises(ValidationError):
        adapter.validate_python({**command, "rebalance_every_sessions": 5})
    command.pop("selection_every_sessions")
    with pytest.raises(ValidationError):
        adapter.validate_python({**command, "rebalance_every_sessions": 5})


@pytest.mark.parametrize("interval", [0, 21, True, 1.5, "5"])
def test_selection_schedule_rejects_invalid_intervals(interval):
    with pytest.raises(ValidationError):
        TypeAdapter(ResearchRunAdmissionCommand).validate_python({
            **strategy_command(), "selection_every_sessions": interval,
        })


@pytest.mark.parametrize("source,expected", [
    ("0", 0.0), ("0.7", 0.7), ("1", 1.0), ("7 / 10", 0.7),
    ("if_else(1 > 0, 0.7, 1 / 0)", 0.7),
])
def test_constant_exposure_uses_shared_expression_semantics(source, expected):
    from thesistrace.alpha_language import ValueType, alpha_language
    from thesistrace.research_kernel.series_plan import (
        build_series_execution_plan,
        evaluate_series_execution_plan,
    )

    compiled = alpha_language.compile(source, context="exposure")
    assert compiled.context == "exposure"
    assert compiled.result_type is ValueType.NUMBER
    assert compiled.field_ids_by_identifier == {}
    assert compiled.effective_lookback == 0
    assert evaluate_series_execution_plan(build_series_execution_plan(compiled), {}) == [expected]
    assert alpha_language.diagnose(source, context="exposure").valid


def test_signal_compilation_preserves_its_context():
    from thesistrace.alpha_language import alpha_language

    assert alpha_language.compile("close").context == "signal"
    assert alpha_language.compile("close", context="signal").context == "signal"


@pytest.mark.parametrize("source", [
    "-0.01", "1.01", "1 / 0", "1e309", "1 > 0", "True", "close",
    "universe_return()", "if_else(close > 0, 0.7, 1)",
])
def test_exposure_rejects_invalid_values_and_data_scopes(source):
    from thesistrace.alpha_language import FormulaCompilationError, alpha_language

    with pytest.raises(FormulaCompilationError):
        alpha_language.compile(source, context="exposure")
    diagnostic = alpha_language.diagnose(source, context="exposure")
    assert not diagnostic.valid
    assert diagnostic.diagnostics
