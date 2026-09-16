"""Independent, fixed-date arithmetic proof for the existing QS4 switch formulas."""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from thesistrace.alpha_language import alpha_language
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.research_kernel.alpha import evaluate_columnar_alpha_matrix
from thesistrace.research_kernel.series_plan import (
    build_series_execution_plan,
    evaluate_columnar_execution_matrix,
)

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
SOURCE_SHA = "4723b071313705df8662131f4ec4137e4cf35a9680a7c63c1a0191eb66e83e7f"
END = "2026-08-27"
KEYS = ("d035", "d036", "d037")
TOLERANCE = 1e-10
plan_path = ROOT / "round28-plan.json"
plan_bytes = plan_path.read_bytes()
plan = json.loads(plan_bytes)
specs = [next(d for d in plan["definitions"] if d["key"] == key) for key in KEYS]
assert all(d["neutralization"] == "none" and d["universe"] == "top3000" for d in specs)
compiled = {d["key"]: alpha_language.compile(d["formula"]) for d in specs}
assert [compiled[key].effective_lookback for key in KEYS] == [120, 119, 120]

source = ROOT / "offline-market"
manifest_path = source / "manifests/sha256" / SOURCE_SHA[:2] / (SOURCE_SHA + ".json")
manifest = json.loads(manifest_path.read_text())
calendar = manifest["research_sessions"]
assert manifest["data_through_session"] == END
last = calendar.index(END)
sessions = calendar[last - 120:last + 1]
assert len(sessions) == 121 and sessions[0] >= "2025-08-01"
data = MountedGenerationStore(source).read_columnar_slice(
    SOURCE_SHA,
    sessions=sessions,
    universe_name="top3000",
    neutralization="none",
    field_bindings={"price.close.adjusted": "close", "market.turnover.cny": "amount"},
    fact_instrument_ids=frozenset(),
)
ids = tuple(sorted(data.instruments))
positions = {iid: index for index, iid in enumerate(ids)}
matrices = data.numeric_field_matrices(
    ("price.close.adjusted", "market.turnover.cny"), ids
)
members = tuple(sorted(data.universe_members[END]))


def complete_mean(values):
    sample = [float(value) for value in values]
    if not sample or not all(map(math.isfinite, sample)):
        return None
    return math.fsum(sample) / len(sample)


def direct_return(current, prior):
    current, prior = float(current), float(prior)
    if not math.isfinite(current) or not math.isfinite(prior) or prior == 0:
        return None
    result = current / prior - 1
    return result if math.isfinite(result) else None


def direct_volatility(prices):
    returns = [direct_return(current, prior) for current, prior in zip(prices[1:], prices[:-1])]
    if not returns or any(value is None for value in returns):
        return None
    # Independent two-pass centered sum of squares; no kernel rolling/std helper.
    mean = math.fsum(returns) / len(returns)
    return math.sqrt(math.fsum((value - mean) ** 2 for value in returns) / len(returns))


def direct_rank(values):
    # Independent order-statistic implementation using binary search for tie bounds.
    ordered_values = sorted(values.values())
    n = len(ordered_values)
    if n == 1:
        return {iid: 0.5 for iid in values}
    return {
        iid: ((bisect_left(ordered_values, value) + bisect_right(ordered_values, value) - 1) / 2)
        / (n - 1)
        for iid, value in values.items()
    }


def finite_sign(value):
    return float((value > 0) - (value < 0))


def state_counts(values, population):
    counts = Counter("positive" if values[iid] > 0 else "negative" if values[iid] < 0 else "zero"
                     for iid in population if iid in values)
    return {key: counts[key] for key in ("negative", "zero", "positive")} | {
        "missing": sum(iid not in values for iid in population)
    }


raw = {key: {} for key in ("ma20", "ma120", "momentum120_skip20", "vol20", "vol120", "amount20", "return5")}
nonpositive_price_cells = 0
for iid in members:
    row = positions[iid]
    prices = matrices["price.close.adjusted"][row]
    amounts = matrices["market.turnover.cny"][row]
    nonpositive_price_cells += sum(math.isfinite(float(p)) and float(p) <= 0 for p in prices)
    values = {
        "ma20": complete_mean(prices[-20:]),
        "ma120": complete_mean(prices[-120:]),
        "momentum120_skip20": direct_return(prices[-21], prices[-121]),
        "vol20": direct_volatility(prices[-21:]),
        "vol120": direct_volatility(prices),
        "amount20": complete_mean(amounts[-20:]),
        "return5": direct_return(prices[-1], prices[-6]),
    }
    for key, value in values.items():
        if value is not None and math.isfinite(value):
            raw[key][iid] = value

leaves = {
    "momentum_rank": direct_rank(raw["momentum120_skip20"]),
    "vol20_rank": direct_rank(raw["vol20"]),
    "amount20_rank": direct_rank(raw["amount20"]),
    "return5_rank": direct_rank(raw["return5"]),
}
moderate_distance = {iid: -abs(value - 0.3) for iid, value in leaves["return5_rank"].items()}
leaves["moderate_rank"] = direct_rank(moderate_distance)
trend_state = {
    iid: finite_sign(raw["ma20"][iid] / raw["ma120"][iid] - 1)
    for iid in members
    if iid in raw["ma20"] and iid in raw["ma120"] and raw["ma120"][iid] != 0
}
vol_state = {
    iid: finite_sign(raw["vol20"][iid] / raw["vol120"][iid] - 1.2)
    for iid in members
    if iid in raw["vol20"] and iid in raw["vol120"] and raw["vol120"][iid] != 0
}
one_minus = lambda values: {iid: 1 - value for iid, value in values.items()}
formula_parts = {
    "d035": (trend_state, leaves["momentum_rank"], one_minus(leaves["vol20_rank"])),
    "d036": (trend_state, one_minus(leaves["amount20_rank"]), one_minus(leaves["vol20_rank"])),
    "d037": (vol_state, one_minus(leaves["vol20_rank"]), leaves["moderate_rank"]),
}
expected = {}
coverage = {}
for key, (state, positive_branch, negative_branch) in formula_parts.items():
    common = state.keys() & positive_branch.keys() & negative_branch.keys()
    expected[key] = {
        iid: ((1 + state[iid]) * positive_branch[iid] + (1 - state[iid]) * negative_branch[iid]) / 2
        for iid in common
    }
    # This checks strict-expression coverage; it does not propose or execute a different strategy.
    selected_branch_has_value = {
        iid for iid in state
        if ((state[iid] > 0 and iid in positive_branch)
            or (state[iid] < 0 and iid in negative_branch)
            or (state[iid] == 0 and iid in positive_branch and iid in negative_branch))
    }
    lost_dormant = sorted(selected_branch_has_value - common)
    coverage[key] = {
        "state_among_current_universe": state_counts(state, members),
        "state_among_final_valid": state_counts(state, common),
        "final_valid": len(common),
        "state_valid": len(state),
        "positive_branch_valid": len(positive_branch),
        "negative_branch_valid": len(negative_branch),
        "selected_branch_finite_but_dormant_branch_missing_count": len(lost_dormant),
        "selected_branch_finite_but_dormant_branch_missing_ids": lost_dormant,
        "state_valid_but_positive_branch_missing": sorted(state.keys() - positive_branch.keys()),
        "state_valid_but_negative_branch_missing": sorted(state.keys() - negative_branch.keys()),
    }


def native_values(formula):
    c = alpha_language.compile(formula)
    result = evaluate_columnar_alpha_matrix(
        data, compiled_alpha=c, neutralization="none", cancellation_check=lambda: None
    )
    item = next(s for s in result["sessions"] if s["session"] == END)
    return {v["instrument_id"]: v["value"] for v in item["values"]}


def compare(key, reference, native):
    common = reference.keys() & native.keys()
    differences = [
        {"instrument_id": iid, "direct": reference[iid], "dsl": native[iid],
         "absolute_error": abs(reference[iid] - native[iid])}
        for iid in sorted(common)
        if abs(reference[iid] - native[iid]) > TOLERANCE
    ]
    result = {
        "key": key,
        "direct_valid": len(reference),
        "dsl_valid": len(native),
        "only_direct": sorted(reference.keys() - native.keys()),
        "only_dsl": sorted(native.keys() - reference.keys()),
        "different_scores_over_tolerance": len(differences),
        "difference_examples": differences[:20],
        "max_absolute_error": max((abs(reference[iid] - native[iid]) for iid in common), default=0.0),
        "exact_score_count": sum(reference[iid] == native[iid] for iid in common),
    }
    print(json.dumps(result), flush=True)
    return result


print(json.dumps({
    "phase": "independent_arithmetic_complete",
    "session": END, "history_start": sessions[0], "session_count": len(sessions),
    "current_research_universe_count": len(members),
    "leaf_valid_counts": {key: len(value) for key, value in raw.items()},
    "state_counts": {key: value["state_among_current_universe"] for key, value in coverage.items()},
}), flush=True)
comparisons = [
    compare(d["key"], expected[d["key"]], native_values(d["formula"])) for d in specs
]
components = [
    ("momentum_rank", "rank(lag(close, 20) / lag(close, 120) - 1)", leaves["momentum_rank"]),
    ("vol20_rank", "rank(ts_std(pct_change(close, 1), 20))", leaves["vol20_rank"]),
    ("amount20_rank", "rank(ts_mean(amount, 20))", leaves["amount20_rank"]),
    ("return5_rank", "rank(pct_change(close, 5))", leaves["return5_rank"]),
    ("moderate_rank", "rank(-abs(rank(pct_change(close, 5)) - 0.3))", leaves["moderate_rank"]),
    ("trend_state", "sign(ts_mean(close, 20) / ts_mean(close, 120) - 1)", trend_state),
    ("vol_state", "sign(ts_std(pct_change(close, 1), 20) / ts_std(pct_change(close, 1), 120) - 1.2)", vol_state),
]
component_comparisons = [compare(key, reference, native_values(formula))
                        for key, formula, reference in components]

probe_instruments = ("finite", "missing")
probe = evaluate_columnar_execution_matrix(
    build_series_execution_plan(alpha_language.compile("0 * close + 1")),
    probe_instruments, (END,),
    {"price.close.adjusted": np.array([[2.0], [np.nan]])},
    {END: probe_instruments},
    cancellation_check=lambda: None,
)
zero_probe = {"formula": "0 * close + 1", "finite_input_result": float(probe[0, 0]),
              "missing_input_result_is_missing": bool(np.isnan(probe[1, 0]))}
assert zero_probe["finite_input_result"] == 1.0 and zero_probe["missing_input_result_is_missing"]
code_paths = (
    "apps/core/src/thesistrace/research_kernel/series_plan.py",
    "apps/core/src/thesistrace/research_kernel/alpha_builtins.py",
    "apps/core/src/thesistrace/research_kernel/alpha.py",
    "apps/core/src/thesistrace/data/columnar_series.py",
    "apps/core/src/thesistrace/data/generation_store.py",
    "apps/core/src/thesistrace/data/fields.py",
)
output = {
    "created_at": datetime.now(timezone.utc).isoformat(),
    "session": END, "source_generation": SOURCE_SHA,
    "source_data_through": manifest["data_through_session"],
    "source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    "history_start": sessions[0], "history_sessions": len(sessions),
    "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
    "checkout_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
    "source_code_sha256": {p: hashlib.sha256((REPO / p).read_bytes()).hexdigest() for p in code_paths},
    "definitions": [{"key": d["key"], "formula": d["formula"],
                     "hypothesis": d["hypothesis"], "compiled_lookback": compiled[d["key"]].effective_lookback,
                     "compiled_nodes": compiled[d["key"]].node_count} for d in specs],
    "universe": "top3000", "neutralization": "none",
    "current_research_universe_count": len(members),
    "nonpositive_price_cells_in_current_members_history": nonpositive_price_cells,
    "leaf_valid_counts": {key: len(value) for key, value in raw.items()},
    "rank_node_valid_counts": {key: len(value) for key, value in leaves.items()},
    "rank_node_members_excluded_from_each_final_formula": {
        key: {leaf: len(values.keys() - expected[key].keys()) for leaf, values in leaves.items()}
        for key in KEYS
    },
    "formula_coverage": coverage,
    "final_comparisons": comparisons,
    "component_comparisons": component_comparisons,
    "zero_times_missing_probe": zero_probe,
    "tolerance": TOLERANCE,
    "verified_final_scores": sum(c["dsl_valid"] for c in comparisons),
    "verified_component_values": sum(c["dsl_valid"] for c in component_comparisons),
    "limitations": [
        "One preselected local date through 2026-08-27, not the latest 2026-09-09 production generation.",
        "Independent arithmetic and order statistics share the current mounted data reader and its Universe eligibility; source bars and Universe construction are not independently audited here.",
        "No strategy return, portfolio market-state, 100000-CNY execution, slippage, board entitlement or profitability claim.",
        "Two-pass reference population standard deviation may differ at floating-point rounding; final ranks/states are compared explicitly.",
        "No market export, MCP submission, container mutation or production source modification.",
    ],
}
bad = [c for c in comparisons + component_comparisons
       if c["only_direct"] or c["only_dsl"] or c["different_scores_over_tolerance"]]
output["status"] = "verified" if not bad else "differences_require_diagnosis"
(ROOT / "round28-switch-proof.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
assert not bad, "Saved signal differences require diagnosis; do not claim verification"
print(json.dumps({"status": output["status"], "final_scores": output["verified_final_scores"],
                  "component_values": output["verified_component_values"]}), flush=True)
