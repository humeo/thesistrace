"""Content-free behavioral oracle using Core's actual Alpha compiler/kernel.

Input is private stdin, never a command-line argument or diagnostic. The four
fixed panels distinguish lookback, price level, compounding and signal direction.
This tests the requested signal semantics, not financial predictive power.
"""
from __future__ import annotations

import json
import math
import sys

from thesistrace.alpha_language import alpha_language
from thesistrace.research_kernel.series_plan import (
    CompiledAlphaLike,
    build_series_execution_plan,
    evaluate_series_execution_matrix,
)

REFERENCES = {
    "momentum": "rank(pct_change(close, 2))",
    "price-rank": "rank(close)",
    "negative-price-rank": "-rank(close)",
    "two-session-mean": "ts_mean(close, 2)",
}
SESSIONS = tuple(f"2026-07-{20 + index:02d}" for index in range(8))
INSTRUMENTS = tuple(f"equity:eval-{index}" for index in range(5))


def formula_meets_outcome(source: str, outcome: str) -> bool:
    reference = alpha_language.compile(REFERENCES[outcome])
    try:
        actual = alpha_language.compile(source)
    except ValueError:
        return False
    if (
        set(actual.field_ids_by_identifier) != {"close"}
        or actual.effective_lookback != reference.effective_lookback
    ):
        return False
    # Fixed, non-monotone and differently scaled histories. No clock, RNG,
    # paid service, database mutation or generated fixture contents.
    panels = [
        {
            instrument: {
                "price.close.adjusted": [
                    float(10 + 7 * index + ((session * (index + 3) + panel * 11) % 17))
                    for session in range(len(SESSIONS))
                ],
            }
            for index, instrument in enumerate(INSTRUMENTS)
        }
        for panel in range(3)
    ]
    # A round trip through a large gain and loss has no compounded gain, but
    # its arithmetic mean return can exceed a steadily rising instrument's.
    panels.append({
        instrument: {"price.close.adjusted": list(history)}
        for instrument, history in zip(INSTRUMENTS, (
            (100.0, 150.0, 100.0, 120.0, 80.0, 160.0, 90.0, 110.0),
            (100.0, 103.0, 106.0, 108.0, 109.0, 112.0, 115.0, 118.0),
            (20.0, 30.0, 21.0, 25.0, 18.0, 33.0, 21.0, 22.0),
            (70.0, 69.0, 67.0, 60.0, 65.0, 59.0, 57.0, 54.0),
            (400.0, 410.0, 430.0, 440.0, 415.0, 418.0, 405.0, 430.0),
        ), strict=True)
    })

    for prices in panels:
        expected_values, actual_values = _evaluate(reference, prices), _evaluate(actual, prices)
        for session in range(reference.effective_lookback, len(SESSIONS)):
            for left in INSTRUMENTS:
                for right in INSTRUMENTS:
                    expected = (expected_values[left][session], expected_values[right][session])
                    observed = (actual_values[left][session], actual_values[right][session])
                    if any(
                        value is None or not math.isfinite(value)
                        for value in (*expected, *observed)
                    ):
                        return False
                    if _order(*expected) != _order(*observed):
                        return False
    return True


def _order(left: float, right: float) -> int:
    return (left > right) - (left < right)


def _evaluate(
    compiled: CompiledAlphaLike, prices: dict[str, dict[str, list[float]]],
) -> dict[str, list[float | None]]:
    return evaluate_series_execution_matrix(
        build_series_execution_plan(compiled),
        list(INSTRUMENTS),
        prices.__getitem__,
        length=len(SESSIONS),
        universe_members={session: INSTRUMENTS for session in SESSIONS},
        sessions=SESSIONS,
    )


def main() -> int:
    try:
        value = json.loads(sys.stdin.read(8193))
        if (
            not isinstance(value, dict)
            or set(value) != {"formula", "outcome"}
            or not isinstance(value["formula"], str)
            or len(value["formula"]) > 4096
            or value["outcome"] not in REFERENCES
        ):
            raise ValueError
        print(json.dumps({"matches": formula_meets_outcome(value["formula"], value["outcome"])}))
        return 0
    except Exception:
        print("RESEARCH_EVAL_FORMULA_ORACLE_FAILED", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
