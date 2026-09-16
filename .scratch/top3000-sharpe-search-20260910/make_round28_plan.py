"""Freeze a finite, performance-independent audit of previously submitted definitions."""
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from thesistrace.alpha_language import alpha_language

ROOT = Path(__file__).resolve().parent
read = lambda p: json.loads(p.read_text())
dump = lambda x: json.dumps(x, ensure_ascii=False, indent=2) + "\n"
plan_path = ROOT / "round28-plan.json"
assert not plan_path.exists(), "The frozen audit must not be overwritten."
context = read(ROOT / "round28-research-context.json")
assert context["data_overview"]["data_through_session"] == "2026-09-09"
records = {p.stem: read(p) for p in (ROOT / "results").glob("*.json")}
runs = {p.stem: read(p) for p in (ROOT / "runs").glob("*.json")}
reference = records["run_47cdfd9fa3b147ff8ae7"]["provenance"]
definitions = {}
manifest = []
files = sorted((ROOT / "submissions").glob("*.json"), key=lambda p: (read(p)["submitted_at"], p.name))
assert not any(p.stem.startswith("r28-") for p in files)

for path in files:
    sub = read(path)
    inp = sub["input"]
    manifest.append({"file": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    for ordinal, item in enumerate(inp.get("factors", [inp.get("alpha", inp)])):
        key = (item["formula"], inp["neutralization"], inp["universe"])
        entry = definitions.setdefault(key, {
            "key": f"d{len(definitions)+1:03d}", "formula": key[0], "neutralization": key[1], "universe": key[2],
            "first_submitted_at": sub["submitted_at"], "hypothesis": item.get("hypothesis"),
            "source_name": item.get("name", item.get("item_key", inp.get("strategies", [{}])[0].get("name", sub["key"]))),
            "sources": [], "original_roles": []})
        entry["sources"].append({"file": str(path.relative_to(ROOT)), "item_key": item.get("item_key"),
            "ordinal": ordinal, "outcome": sub["response"].get("outcome"),
            "original_start": inp["start_date"], "original_end": inp["end_date"]})

def walk(obj):
    if isinstance(obj, dict):
        if isinstance(obj.get("formula"), str):
            yield obj
        for value in obj.values():
            yield from walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk(value)

for path in sorted(ROOT.glob("*plan.json")):
    for item in walk(read(path)):
        role = item.get("role")
        if role:
            for entry in definitions.values():
                if entry["formula"] == item["formula"]:
                    entry["original_roles"].append({"file": path.name, "role": role})

target = {"start_date": "2025-09-10", "end_date": "2026-09-09", "universe": "top3000"}
cfgs = [{"holdings_count": n, "rebalance_every_sessions": 20} for n in (10, 20)]
blocked = {
    "rank(revenue / assets - lag(revenue / assets, 252) + 0 * log(assets) + 0 * log(lag(assets, 252)))":
        ["run_c17b5a72dc0d483da801", "run_4cfbc3af66b84752ac4c"],
    "rank(delta(revenue / assets + 0 * log(assets), 252))":
        ["run_164b822dc3dd48c98c1c"],
}
positive = lambda value: value is not None and math.isfinite(value) and value > 0

def matching_factor(record, entry):
    inp = record["run"]["input"]
    prov = record["provenance"]
    return (all(inp[k] == v for k, v in target.items()) and inp["formula"] == entry["formula"]
        and inp["neutralization"] == entry["neutralization"]
        and prov["authoring_input"] == inp and prov["data"] == reference["data"]
        and prov["execution"]["semantic_versions"] == reference["execution"]["semantic_versions"]
        and prov["execution"]["calculation_contracts"]["numeric_execution_contract"]
            == reference["execution"]["calculation_contracts"]["numeric_execution_contract"])

def classify(record):
    horizon = record["factor"]["factor"]["horizons"]["20"]
    summary = horizon["summary"]
    coverage = horizon["coverage"]
    conditions = {"rank_ic_positive": positive(summary["rank_ic"]["mean"]),
        "q5_positive": positive(summary["quantile_returns"]["q5"]),
        "paired_spread_positive": positive(summary["top_bottom_return"]),
        "coverage90": coverage["signal_session_count"] > 0 and
            coverage["rank_ic_valid_session_count"] / coverage["signal_session_count"] >= .9}
    if any(summary[k] is None for k in ("top_bottom_return",)) or summary["rank_ic"]["mean"] is None or summary["quantile_returns"]["q5"] is None or not conditions["coverage90"]:
        category = "metric_unavailable_or_low_coverage"
    elif all(conditions.values()):
        category = "old_gate_pass"
    elif all(v for k, v in conditions.items() if k != "rank_ic_positive"):
        category = "only_ic_fails"
    else:
        category = "q5_or_spread_also_fails"
    return {"source_run_id": record["run"]["id"], "category": category, "conditions": conditions,
        "rank_ic20": summary["rank_ic"]["mean"], "q5_20": summary["quantile_returns"]["q5"],
        "paired_spread20": summary["top_bottom_return"], "coverage": coverage}

cases = []
for entry in definitions.values():
    compiled = alpha_language.compile(entry["formula"])
    entry["compiled"] = {"lookback": compiled.effective_lookback, "nodes": compiled.node_count,
        "work": compiled.estimated_work, "field_ids": compiled.field_ids_by_identifier}
    entry["status_at_freeze"] = "prior_resource_failure" if entry["formula"] in blocked else "eligible"
    entry["blocked_evidence"] = blocked.get(entry["formula"], [])
    for rid in entry["blocked_evidence"]:
        assert runs[rid]["status"] == "failed"
    entry["execution_route"] = ("single" if compiled.effective_lookback == 252
        and any(f.startswith("financial.") for f in compiled.field_ids_by_identifier.values()) else "batch")
    matched = sorted([r for r in records.values() if matching_factor(r, entry)],
        key=lambda r: (r["run"]["created_at"], r["run"]["id"]))
    entry["preexisting_year_factor_run_ids"] = [r["run"]["id"] for r in matched]
    entry["old_gate_at_freeze"] = classify(matched[0]) if matched else {"category": "no_same_year_factor"}
    if matched:
        assert all(r["factor"]["factor"] == matched[0]["factor"]["factor"] for r in matched)
    for cfg in cfgs:
        exact = [r for r in matched if "summary" in r and all(r["run"]["input"][k] == v for k, v in cfg.items())]
        for r in exact:
            contracts = r["provenance"]["execution"]["calculation_contracts"]
            assert contracts["costs"] == reference["execution"]["calculation_contracts"]["costs"]
            assert contracts["risk_free_rate"] == "0"
            assert contracts["strategy"] == {**reference["execution"]["calculation_contracts"]["strategy"], **cfg}
            assert float(r["summary"]["initial_cash_cny"]) == 10000000
        status = "reused" if exact else ("unresolved_prior_resource_failure" if entry["status_at_freeze"] != "eligible" else "planned")
        cases.append({"case_key": entry["key"] + f"-h{cfg['holdings_count']}r20", "definition_key": entry["key"],
            **cfg, "status_at_freeze": status, "reused_run_ids": [r["run"]["id"] for r in exact]})

plan = {"round": 28, "created_at": datetime.now(timezone.utc).isoformat(),
    "status": "frozen_before_new_account_results", "purpose": "Audit previous factor-gate omissions in all finite previously submitted definitions, with uniform actual-account probes.",
    "method_review": "ROUND28_METHOD_REVIEW.md", "scope": "All formula/neutralization/universe definitions in the 129 saved pre-QS28 submission files; includes rejected attempts and controls, excludes never-submitted ideas.",
    "source_manifest": manifest, "source_manifest_sha256": hashlib.sha256(dump(manifest).encode()).hexdigest(),
    **target, "data": reference["data"], "benchmark_snapshot_sha256": context["data_overview"]["benchmark_snapshot_sha256"],
    "execution_reference": reference["execution"], "configurations": cfgs, "definitions": list(definitions.values()), "cases": cases,
    "selection": {"factor_metrics_used_for_admission": False, "eligibility": "Unchanged causal compiled definition; complete required history from pinned native dataset; original none/industry. Prior unresolved resource failures retained, not retried.",
        "ordering": "First prior submission timestamp, source file name, item ordinal; stable across performance.",
        "within_definition_order": "H10 then H20; reuse exact frozen cases; no performance-dependent parameter changes.",
        "native_year_pass": {"sharpe_strictly_greater_than": 1.2, "maximum_drawdown_at_most": .2},
        "followups_if_native_year_pass": [
            {"start_date": "2023-09-11", "end_date": "2026-09-09", "same_holdings_and_rebalance": True},
            {"start_date": "2026-06-11", "end_date": "2026-09-09", "same_holdings_and_rebalance": True}],
        "followup_reuse": "Same formula, universe, neutralization, dates, N/R, data generation, benchmark and calculation contracts only.",
        "native_pass_audit": "Collect complete paginated NAV; independently recompute Sharpe, drawdown, costs and net return; retain quarter fresh-start vs continuous-year distinction.",
        "capital": "100000 CNY, no leverage, drawdown<=20%; native10000000 is only prescreen. Use only already-authorized matching local history for capital replay. Latest raw export and board access remain pending.",
        "stop_rule": "Runtime resource failure: record unresolved and do not retry unchanged input or dispatch remaining N for that definition. Rejected batch resource admission: exact unchanged single jobs allowed once; do not shorten history/universe. Data or contract drift pauses new submissions until separately reconciled.",
        "reporting": "All outcomes, controls, formula variants and previous trials retained; audit compares categories of old factor gate, not new independent families. No previously examined period is called unseen out-of-sample.",
        "scheduling": "Bound in-flight submissions; resource scheduling may delay a fixed inventory item without changing its eligibility or input."},
    "counts_at_freeze": {"submission_files": len(files), "definitions": len(definitions),
        "literal_formulas": len({k[0] for k in definitions}), "cases": len(cases),
        "case_statuses": dict(Counter(c["status_at_freeze"] for c in cases)),
        "gate_definition_categories": dict(Counter(e["old_gate_at_freeze"]["category"] for e in definitions.values()))}}
assert len(files) == 129 and len(definitions) == 109
assert all(e["universe"] == "top3000" for e in definitions.values())
plan_path.write_text(dump(plan))
print(dump(plan["counts_at_freeze"]))
print("planned_prefix", [c["case_key"] for c in cases if c["status_at_freeze"] == "planned"][:30])
