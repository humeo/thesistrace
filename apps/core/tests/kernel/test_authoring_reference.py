from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from thesistrace.alpha_language import alpha_language
from thesistrace.research_authoring import ResearchAuthoringService
from thesistrace.research_history import HistoryWindow
from thesistrace.research_kernel.strategy_decision import program_target
from thesistrace.research_kernel.strategy_program_runtime import get_strategy_runtime


def test_reference_publishes_the_complete_formula_operator_contract():
    entry = ResearchAuthoringService().reference("formula", "syntax").entry
    assert entry.constraints["operators"] == {
        "arithmetic": ["+", "-", "*", "/"],
        "comparison": [">", ">=", "<", "<=", "==", "!="],
        "unary": ["-", "not"],
        "boolean": ["and", "or"],
    }
    for expression in ("close + open", "close - open", "close * 2", "close / open", "-close",
                       "if_else(not (close > open), close, open)",
                       "if_else(close >= open and close != open, close, open)",
                       "if_else(close < open or close <= open or close == open, close, open)"):
        assert alpha_language.diagnose(expression).valid, expression
    for expression in ("close ** 2", "close % 2", "close // 2", "+close", "True",
                       "if_else(0 < close < 100, close, open)", "close[0]", "data.close",
                       "ts_mean(close, window=2)"):
        assert not alpha_language.diagnose(expression).valid, expression


def test_reference_covers_every_shipped_public_sdk_class_method_and_attribute():
    service = ResearchAuthoringService()
    entries = {item.symbol for item in service.reference("python_sdk").symbols}
    assert {"History.array", "History.instruments"} <= entries
    assert not any(name.startswith("_") for name in entries)
    source = Path(__file__).parents[2] / "src/thesistrace/research_kernel/strategy_sdk.py"
    for node in ast.parse(source.read_text()).body:
        if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
            continue
        assert node.name in entries
        for member in node.body:
            if isinstance(member, ast.FunctionDef) and (
                not member.name.startswith("_") or member.name == "__getitem__"
            ):
                detail = service.reference("python_sdk", f"{node.name}.{member.name}").entry
                assert detail.signature
                assert detail.returns
            if isinstance(member, ast.FunctionDef) and member.name == "__init__":
                for assignment in ast.walk(member):
                    if not isinstance(assignment, ast.Assign):
                        continue
                    for target in assignment.targets:
                        if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                                and target.value.id == "self" and not target.attr.startswith("_")):
                            assert f"{node.name}.{target.attr}" in entries
    for topic in service.guide().topics:
        for summary in service.reference(topic.topic).symbols:
            detail = service.reference(topic.topic, summary.symbol)
            assert detail.found and detail.entry.description
            assert len(detail.model_dump_json().encode()) <= 64 * 1024


@pytest.mark.bounded_process
def test_documented_examples_execute_in_the_real_guest_and_use_legal_decisions():
    service = ResearchAuthoringService()
    runtime = get_strategy_runtime()
    context = {
        "session": "2026-09-01", "completed_sessions": 1,
        "account": {"positions": [], "cash_cny": "100000",
                    "post_open_net_nav_cny": "100000", "close_risk_nav_cny": "100000"},
        "candidates": [{"instrument_id": "equity:600001.SH", "board": "main", "industry": None}],
        "framework": {"signals": [{"instrument_id": "equity:600001.SH", "value": 1.0}]},
    }
    observed = {}
    for topic in ("examples", "python_sdk", "formula"):
        for symbol in service.reference(topic).symbols:
            for example in service.reference(topic, symbol.symbol).entry.examples:
                if example.language == "formula":
                    assert alpha_language.diagnose(example.source, context=example.context).valid
                    continue
                runtime.validate(example.source, entrypoint=example.entrypoint)
                result = runtime.invoke(
                    example.source, entrypoint=example.entrypoint, state={}, context=context,
                    read_history=lambda _request: HistoryWindow(
                        ("2026-08-31", "2026-09-01"), ("equity:600001.SH",),
                        np.array([[10.0, 11.0]]),
                    ),
                )
                if example.entrypoint in {"Strategy", "PortfolioConstruction"}:
                    program_target(result.output, context, "a" * 64)
                observed[symbol.symbol] = result.output
    assert observed["Strategy.increase_to_weights"]["allocation"]["mode"] == "increase"
    assert observed["Strategy.reduce_exposure"]["allocation"]["mode"] == "reduce"
    assert observed["Strategy.with_limits"]["maximum_stock_exposure"] == 0.5
    assert observed["RiskManagement.replace"]["target"]["allocation"]["instrument_ids"] == []


def test_reference_results_do_not_share_mutable_document_state():
    service = ResearchAuthoringService()
    first = service.reference("python_sdk", "Data.history")
    first.entry.parameters.clear()
    assert "field_id" in service.reference("python_sdk", "Data.history").entry.parameters
