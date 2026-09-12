from dataclasses import replace
from datetime import date

import pytest

from thesistrace.alpha_language import alpha_language
from thesistrace.data.admission import DatasetAdmissionSnapshot
from thesistrace.research_run.models import FactorEvaluationAdmissionCommand
from thesistrace.research_run.service import ResearchRunAdmissionRejected, _admitted_input


def inputs(source, neutralization="none"):
    days = tuple(date(2026, 8, day) for day in range(3, 8))
    compiled = alpha_language.compile(source)
    command = FactorEvaluationAdmissionCommand(
        request_id="coverage",
        folder_id="folder_default",
        formula=source,
        research_kind="factor_evaluation",
        start_date=days[-1].isoformat(),
        end_date=days[-1].isoformat(),
        universe="top300",
        neutralization=neutralization,
    )
    snapshot = DatasetAdmissionSnapshot(
        generation_manifest_sha256="a" * 64,
        data_through_session=days[-1],
        coverage_start=days[0],
        coverage_end=days[-1],
        research_sessions=days,
        available_field_ids=frozenset({"price.close.adjusted"}),
        maximum_universe_cardinality=lambda *_: 1,
        universe_member_union_cardinalities=lambda _universe, windows: tuple(1 for _ in windows),
        financial_research_readiness="not_ready",
        industry_coverage_start=days[2],
        industry_coverage_end=days[-1],
    )
    return command, compiled, snapshot


def test_common_industry_requires_its_calculation_history_and_points_to_formula():
    command, compiled, snapshot = inputs("close * ts_mean(industry_return(801010), 3)")
    with pytest.raises(ResearchRunAdmissionRejected) as caught:
        _admitted_input(command, compiled, snapshot, execution_memory_bytes=1536 * 1024**2)
    issue = caught.value.issues[0]
    assert issue.code == "INDUSTRY_CALCULATION_OUTSIDE_COVERAGE"
    assert issue.field == "formula"
    assert issue.range is not None
    assert issue.range.start.offset == 0
    assert issue.range.end.offset == len(command.formula)
    ready = replace(snapshot, industry_coverage_start=snapshot.coverage_start)
    admitted = _admitted_input(command, compiled, ready, execution_memory_bytes=1536 * 1024**2)
    assert admitted.alpha_admission.effective_lookback == 3


def test_neutralization_without_common_industry_keeps_requested_period_coverage():
    command, compiled, snapshot = inputs("ts_mean(close, 3)", "industry")
    admitted = _admitted_input(command, compiled, snapshot, execution_memory_bytes=1536 * 1024**2)
    assert admitted.neutralization == "industry"


@pytest.mark.parametrize("source", ["1", "0", "7 / 10"])
def test_fixed_exposure_is_compiled_and_frozen_with_strategy_input(source):
    from thesistrace.research_run.models import StrategyBacktestAdmissionCommand

    factor, compiled, snapshot = inputs("close")
    command = StrategyBacktestAdmissionCommand.model_validate({
        **factor.model_dump(), "research_kind": "strategy_backtest",
        "initial_cash_cny": "100000", "holdings_count": 10,
        "selection_every_sessions": 5, "exposure_expression": source,
    })
    admitted = _admitted_input(command, compiled, snapshot, execution_memory_bytes=1536 * 1024**2)
    assert admitted.strategy["exposure_source"] == source
    assert admitted.strategy["exposure_expression"] == alpha_language.compile(
        source, context="exposure",
    ).expression
    assert admitted.alpha_admission.effective_lookback == 0
    assert admitted.requested_start_date == command.start_date


@pytest.mark.parametrize("source", ["1.1", "1 / 0", "close", "universe_return()"])
def test_invalid_exposure_is_rejected_by_shared_admission(source):
    from thesistrace.research_run.models import StrategyBacktestAdmissionCommand

    factor, compiled, snapshot = inputs("close")
    command = StrategyBacktestAdmissionCommand.model_validate({
        **factor.model_dump(), "research_kind": "strategy_backtest",
        "initial_cash_cny": "100000", "holdings_count": 10,
        "selection_every_sessions": 5, "exposure_expression": source,
    })
    with pytest.raises(ResearchRunAdmissionRejected) as caught:
        _admitted_input(command, compiled, snapshot, execution_memory_bytes=1536 * 1024**2)
    assert caught.value.issues[0].field == "exposure_expression"
    assert caught.value.issues[0].range is not None


def test_whole_spec_diagnosis_reuses_admission_and_has_no_persistence_side_effects():
    from uuid import UUID

    from thesistrace.research_run.models import (
        FactorEvaluationSpec,
        StrategyBacktestSpec,
    )
    from thesistrace.research_run.service import ResearchRunService

    class NoPersistence:
        def __getattr__(self, name):
            raise AssertionError(f"Diagnosis attempted persistence: {name}")

    command, _, snapshot = inputs("close")
    service = ResearchRunService(
        NoPersistence(), compile_formula=alpha_language.compile,
        current_dataset=lambda: snapshot,
    )
    values = command.model_dump(exclude={"request_id", "folder_id", "name"})
    factor = FactorEvaluationSpec.model_validate(values)
    assert service.diagnose_research_spec(factor).valid
    strategy = StrategyBacktestSpec.model_validate({
        **values, "research_kind": "strategy_backtest", "initial_cash_cny": "100000",
        "holdings_count": 10, "selection_every_sessions": 5, "exposure_expression": "1.1",
    })
    rejected = service.diagnose_research_spec(strategy)
    assert not rejected.valid
    assert rejected.issues[0].field == "exposure_expression"
    assert rejected.issues[0].range is not None
    # Formal preparation rejects the same configuration through the shared path.
    from thesistrace.research_run.models import StrategyBacktestAdmissionCommand
    submission = StrategyBacktestAdmissionCommand.model_validate({
        **strategy.model_dump(), "request_id": "submit", "folder_id": "folder_default",
    })
    with pytest.raises(ResearchRunAdmissionRejected) as caught:
        service.prepare_child_admission(UUID(int=1), submission, dataset=snapshot)
    assert caught.value.issues == rejected.issues
    # Diagnosis is advisory; preparation sees the current coverage, never a cached success.
    assert service.diagnose_research_spec(factor).valid
    with pytest.raises(ResearchRunAdmissionRejected):
        service.prepare_child_admission(UUID(int=1), command, dataset=None)
