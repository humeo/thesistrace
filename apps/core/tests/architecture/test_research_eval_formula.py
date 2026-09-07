from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ORACLE = (
    Path(__file__).resolve().parents[4] / "tests" / "e2e" / "support" / "research_eval_formula.py"
)
SPEC = importlib.util.spec_from_file_location("research_eval_formula", ORACLE)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize(
    ("formula", "outcome", "expected"),
    [
        ("rank(pct_change(close, 2))", "momentum", True),
        ("close / lag(close, 2) - 1", "momentum", True),
        ("100 * pct_change(close, 2)", "momentum", True),
        ("rank(pct_change(close, 1))", "momentum", False),
        ("rank(close - lag(close, 2))", "momentum", False),
        ("rank(ts_mean(pct_change(close, 1), 2))", "momentum", False),
        ("-rank(pct_change(close, 2))", "momentum", False),
        ("rank(close)", "momentum", False),
        ("rank(close)", "price-rank", True),
        ("rank(log(close)) + 3", "price-rank", True),
        ("-rank(close)", "price-rank", False),
        ("rank(volume)", "price-rank", False),
        ("close - close", "price-rank", False),
        ("rank(-close)", "negative-price-rank", True),
        ("-close", "negative-price-rank", True),
        ("rank(close)", "negative-price-rank", False),
        ("rank(not_a_market_field)", "price-rank", False),
        ("ts_mean(close, 2)", "two-session-mean", True),
        ("rank(ts_mean(close, 2))", "two-session-mean", True),
        ("ts_mean(close, 3)", "two-session-mean", False),
        ("close", "two-session-mean", False),
    ],
)
def test_formula_oracle_checks_behavior_not_exact_program_text(
    formula: str, outcome: str, expected: bool,
) -> None:
    assert MODULE.formula_meets_outcome(formula, outcome) is expected


def test_formula_oracle_cli_keeps_invalid_private_input_out_of_diagnostics() -> None:
    completed = subprocess.run(
        [sys.executable, str(ORACLE)], input="private-eval-canary", text=True,
        capture_output=True, check=False, timeout=10,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == "RESEARCH_EVAL_FORMULA_ORACLE_FAILED\n"
