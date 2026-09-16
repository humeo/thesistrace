"""Verify continuous MA ratios and matched coverage from independent price means."""
import json
import math
from pathlib import Path

import numpy as np

from thesistrace.alpha_language import alpha_language
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.research_kernel.alpha import evaluate_columnar_alpha_matrix

ROOT = Path(__file__).resolve().parent
plan = json.loads((ROOT / "round27-plan.json").read_text())
sha = "4723b071313705df8662131f4ec4137e4cf35a9680a7c63c1a0191eb66e83e7f"
source = ROOT / "offline-market"
calendar = json.loads((source / "manifests/sha256" / sha[:2] / (sha + ".json")).read_text())["research_sessions"]
compiled = [alpha_language.compile(f["formula"]) for f in plan["factors"]]
assert all(c.effective_lookback == 199 for c in compiled)
store = MountedGenerationStore(source)

def ranks(values):
    ordered = sorted(values, key=lambda iid: values[iid]); result = {}; a = 0; n = len(ordered)
    while a < n:
        b = a + 1
        while b < n and values[ordered[b]] == values[ordered[a]]:
            b += 1
        value = .5 if n == 1 else (a + b - 1) / (2 * (n - 1))
        for iid in ordered[a:b]:
            result[iid] = value
        a = b
    return result

comparisons, overlaps, correlations, identity = [], [], [], []
for end in plan["proof"]["planned_dates"]:
    last = calendar.index(end); sessions = calendar[last - 199:last + 1]
    assert len(sessions) == 200 and sessions[0] >= "2025-08-01"
    data = store.read_columnar_slice(sha, sessions=sessions, universe_name="top3000", neutralization="none",
        field_bindings={"price.close.adjusted": "close"}, fact_instrument_ids=frozenset())
    ids = tuple(sorted(data.instruments)); indices = {iid: i for i, iid in enumerate(ids)}
    matrix = data.numeric_field_matrices(("price.close.adjusted",), ids)["price.close.adjusted"]
    expected_raw = {f["item_key"]: {} for f in plan["factors"]}
    errors = []
    for iid in sorted(data.universe_members[end]):
        prices = matrix[indices[iid]]
        if not np.isfinite(prices).all():
            continue
        assert (prices > 0).all(), "Unexpected nonpositive market price requires separate treatment"
        mean21 = math.fsum(float(v) for v in prices[-21:]) / 21
        mean200 = math.fsum(float(v) for v in prices) / 200
        mrat = mean21 / mean200
        expected_raw["mrat21_200"][iid] = mrat
        expected_raw["momentum120_skip20_history200"][iid] = float(prices[-21] / prices[-121] - 1)
        expected_raw["price_to_ma200"][iid] = float(prices[-1] / mean200)
        errors.append(abs(mrat - (float(prices[-1]) / mean200) / (float(prices[-1]) / mean21)))
    native = {}
    for spec, c in zip(plan["factors"], compiled):
        key = spec["item_key"]
        alpha = evaluate_columnar_alpha_matrix(data, compiled_alpha=c, neutralization="none", cancellation_check=lambda: None)
        values = next(s["values"] for s in alpha["sessions"] if s["session"] == end)
        actual = {v["instrument_id"]: v["value"] for v in values}; native[key] = actual
        expected = ranks(expected_raw[key]); unmatched = sorted(expected.keys() ^ actual.keys())
        diffs = [{"id": iid, "expected": expected[iid], "kernel": actual[iid]}
            for iid in sorted(expected.keys() & actual.keys()) if abs(expected[iid] - actual[iid]) > 1e-10]
        comparisons.append({"session": end, "history_start": sessions[0], "key": key,
            "expected_valid": len(expected), "native_valid": len(actual), "unmatched": unmatched,
            "differing_scores": len(diffs), "examples": diffs[:10],
            "max_rank_error": max((abs(expected[i] - actual[i]) for i in expected.keys() & actual.keys()), default=0)})
    assert all(native[key].keys() == native["mrat21_200"].keys() for key in native)
    identity.append({"session": end, "max_algebra_error": max(errors)})
    for control in ("momentum120_skip20_history200", "price_to_ma200"):
        common = sorted(native["mrat21_200"])
        rho = float(np.corrcoef([native["mrat21_200"][i] for i in common], [native[control][i] for i in common])[0, 1])
        correlations.append({"session": end, "control": control, "rank_correlation": rho})
        for n in (10, 20):
            a = set(sorted(common, key=lambda i: (-native["mrat21_200"][i], i))[:n])
            b = set(sorted(common, key=lambda i: (-native[control][i], i))[:n])
            overlaps.append({"session": end, "n": n, "control": control, "common_names": len(a & b)})
    print(json.dumps({"session": end, "comparisons": comparisons[-3:]}), flush=True)
out = {"source_generation": sha, "source_end": "2026-08-27", "planned_dates": plan["proof"]["planned_dates"],
    "comparisons": comparisons, "signal_rank_correlations": correlations, "signal_top_name_overlap": overlaps,
    "algebra_identity": identity, "scored_values": sum(c["native_valid"] for c in comparisons),
    "compiled": [{"key": f["item_key"], "lookback": c.effective_lookback, "nodes": c.node_count, "work": c.estimated_work}
        for f, c in zip(plan["factors"], compiled)],
    "limitations": "Two predetermined fullywarmed local dates; independent means/ranks verify signal calculation only. Signal overlap is not executedportfolio dependence or futureeconomicproof. No latestexport, nofullMADthreshold, no capital replay."}
(ROOT / "round27-signal-proof.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
assert not any(c["unmatched"] or c["differing_scores"] for c in comparisons), "Saved score differences require diagnosis"
assert all(c["max_algebra_error"] < 1e-12 for c in identity)
print(json.dumps({"status": "verified", "scored_values": out["scored_values"]}), flush=True)
