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
