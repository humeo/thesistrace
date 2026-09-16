"""Audit saved QS28 native-account evidence against its immutable finite protocol."""
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
read = lambda p: json.loads(p.read_text())
dump = lambda x: json.dumps(x, ensure_ascii=False, indent=2) + "\n"
plan_bytes = (ROOT / "round28-plan.json").read_bytes()
plan = json.loads(plan_bytes)
plan_sha = hashlib.sha256(plan_bytes).hexdigest()
records = {p.stem: read(p) for p in (ROOT / "results").glob("*.json")}
batches = {p.stem: read(p) for p in (ROOT / "batches").glob("*.json")}
runs = {p.stem: read(p) for p in (ROOT / "runs").glob("*.json")}
definitions = {e["key"]: e for e in plan["definitions"]}
admission_resolutions = read(ROOT / 'round28-admission-resolutions.json') if (ROOT / 'round28-admission-resolutions.json').exists() else {}
ACTIVE = {"queued", "running", "cancelling"}
pending, unknown, uncollected, failed, current_ids, admission_rejected = [], [], [], [], set(), []
attempted_cases, failed_definitions = {}, set()
source_checked = 0
for item in plan["source_manifest"]:
    assert hashlib.sha256((ROOT / item["file"]).read_bytes()).hexdigest() == item["sha256"]
    source_checked += 1
for p in (ROOT / "submissions").glob("r28-*.json"):
    sub = read(p)
    assert sub["source_plan_sha256"] == plan_sha
    response = sub["response"]
    if response.get("outcome") != "accepted":
        resolution = admission_resolutions.get(sub['key'])
        if resolution:
            assert resolution['source_plan_sha256'] == plan_sha
            assert resolution['rejected_submission_sha256'] == hashlib.sha256(p.read_bytes()).hexdigest()
        admission_rejected.append({"file": p.name, "response": response, "reviewed_resolution": resolution})
        continue
    submitted_cfgs = sub['input'].get('strategies', [sub['input']])
    for cfg in submitted_cfgs:
        if sub['input']['start_date'] == plan['start_date'] and sub['input']['end_date'] == plan['end_date']:
            case_key = sub['definition_key'] + f"-h{cfg['holdings_count']}r{cfg['rebalance_every_sessions']}"
            attempted_cases[case_key] = {'submission': p.name, 'status': 'accepted_unobserved'}
    if "batch_id" in response:
        bid = response["batch_id"]
        batch = batches.get(bid)
        if batch is None:
            unknown.append(bid); pending.append(bid); continue
        if batch["status"] in ACTIVE:
            pending.append(bid)
        items = batch["items"]
    else:
        rid = response["run_id"]
        run = runs.get(rid)
        if run is None:
            unknown.append(rid); pending.append(rid)
        elif run["status"] in ACTIVE:
            pending.append(rid)
        items = [{"research_run_id": rid, "status": run["status"] if run else None}]
    for item in items:
        rid = item["research_run_id"]; current_ids.add(rid)
        cfg = next((c for c in submitted_cfgs if c.get('item_key') == item.get('item_key')), submitted_cfgs[0])
        if sub['input']['start_date'] == plan['start_date'] and sub['input']['end_date'] == plan['end_date']:
            case_key = sub['definition_key'] + f"-h{cfg['holdings_count']}r{cfg['rebalance_every_sessions']}"
            attempted_cases[case_key] = {'submission': p.name, 'run_id': rid, 'status': item['status']}
        if item["status"] == "succeeded" and rid not in records:
            uncollected.append(rid)
        if item["status"] == "failed":
            failed.append(rid)
            failed_definitions.add(sub['definition_key'])

positive = lambda x: x is not None and math.isfinite(x) and x > 0
def gate(record):
    h = record["factor"]["factor"]["horizons"]["20"]; s = h["summary"]; c = h["coverage"]
    conditions = [positive(s["rank_ic"]["mean"]), positive(s["quantile_returns"]["q5"]),
        positive(s["top_bottom_return"]), c["signal_session_count"] > 0 and
        c["rank_ic_valid_session_count"] / c["signal_session_count"] >= .9]
    if not conditions[-1] or any(v is None for v in (s["rank_ic"]["mean"], s["quantile_returns"]["q5"], s["top_bottom_return"])):
        category = "metric_unavailable_or_low_coverage"
    elif all(conditions):
        category = "old_gate_pass"
    elif all(conditions[1:]):
        category = "only_ic_fails"
    else:
        category = "q5_or_spread_also_fails"
    return {"category": category, "rank_ic20": s["rank_ic"]["mean"],
        "q5_20": s["quantile_returns"]["q5"], "paired_spread20": s["top_bottom_return"],
        "coverage": c}

def matches(r, entry, cfg, dates):
    i = r["run"]["input"]
    return "summary" in r and all(i[k] == v for k, v in {
        "formula": entry["formula"], "neutralization": entry["neutralization"],
        "universe": "top3000", **cfg, **dates}.items())

def verify(r, cfg):
    prov = r["provenance"]; i = r["run"]["input"]; summary = r["summary"]
    assert prov["authoring_input"] == i
    assert prov["data"] == plan["data"], r["run"]["id"] + " data drift"
    expected = json.loads(json.dumps(plan["execution_reference"]))
    expected["calculation_contracts"]["strategy"].update(cfg)
    assert prov["execution"] == expected, r["run"]["id"] + " execution drift"
    assert float(summary["initial_cash_cny"]) == 10000000
    if summary["comparison"]["status"] == "available":
        assert summary["comparison"]["benchmark"]["snapshot_sha256"] == plan["benchmark_snapshot_sha256"]
    else:
        raise AssertionError("Frozen benchmark unavailable")
    assert r["run"]["status"] == "succeeded" and r["run"]["result_available"]

case_rows, missing, passes, followups, comparisons = [], [], [], [], []
for case in plan["cases"]:
    entry = definitions[case["definition_key"]]
    cfg = {k: case[k] for k in ("holdings_count", "rebalance_every_sessions")}
    dates = {k: plan[k] for k in ("start_date", "end_date")}
    candidates = sorted([r for r in records.values() if matches(r, entry, cfg, dates)],
        key=lambda r: (r["run"]["created_at"], r["run"]["id"]))
    if not candidates:
        missing.append(case)
        continue
    for r in candidates:
        verify(r, cfg)
    r = candidates[0]; m = r["summary"]["metrics"]
    g = gate(r)
    for rid in entry["preexisting_year_factor_run_ids"]:
        assert r["factor"]["factor"] == records[rid]["factor"]["factor"], "Factor changed with strategy"
        comparisons.append({"actual_run_id": r["run"]["id"], "source_run_id": rid, "exact": True})
    passed = m["sharpe"] is not None and math.isfinite(m["sharpe"]) and m["sharpe"] > 1.2 and m["maximum_drawdown"]["value"] <= .2
    row = {**case, "run_id": r["run"]["id"], "all_exact_run_ids": [x["run"]["id"] for x in candidates],
        "source_name": entry["source_name"], "neutralization": entry["neutralization"],
        "new_in_round": r["run"]["id"] in current_ids, "old_gate": g,
        "net_return": m["net_cumulative_return"], "sharpe": m["sharpe"],
        "maximum_drawdown": m["maximum_drawdown"]["value"],
        "fees_cny_at_10m": m["transaction_costs"]["cumulative_amount"],
        "cash_ratio_mean": m["cash_ratio"]["mean"], "actual_holdings_mean": m["holdings_count"]["mean"],
        "native_year_pass": passed}
    case_rows.append(row)
    if passed:
        passes.append(row)
        for period in plan["selection"]["followups_if_native_year_pass"]:
            follow_dates = {k: period[k] for k in ("start_date", "end_date")}
            prior = sorted([q for q in records.values() if matches(q, entry, cfg, follow_dates)], key=lambda q: q["run"]["created_at"])
            for q in prior:
                verify(q, cfg)
            followups.append({"case_key": case["case_key"], **follow_dates,
                "run_ids": [q["run"]["id"] for q in prior], "status": "collected" if prior else "required"})
counts = Counter(row["old_gate"]["category"] for row in case_rows)
passing_counts = Counter(row["old_gate"]["category"] for row in passes)
unsubmitted_cases, unfinished_cases, unresolved_cases = [], [], []
for case in missing:
    attempt = attempted_cases.get(case['case_key'])
    if case['status_at_freeze'] == 'unresolved_prior_resource_failure':
        unresolved_cases.append({**case, 'reason': 'prior_resource_failure_no_retry'})
    elif attempt:
        if attempt['status'] in {'failed', 'cancelled'}:
            unresolved_cases.append({**case, 'reason': 'new_execution_failure_or_cancellation', 'attempt': attempt})
        else:
            unfinished_cases.append({**case, 'attempt': attempt})
    elif case['definition_key'] in failed_definitions:
        unresolved_cases.append({**case, 'reason': 'not_dispatched_after_same_definition_failed'})
    else:
        unsubmitted_cases.append(case)
state = {"updated_at": datetime.now(timezone.utc).isoformat(), "status": "finite_audit_in_progress",
    "plan_sha256": plan_sha, "source_manifest_files_verified": source_checked,
    "fixed_definition_count": len(definitions), "fixed_year_cases": len(plan["cases"]),
    "collected_year_cases": len(case_rows), "new_year_results": sum(r["new_in_round"] for r in case_rows),
    "reused_year_results": sum(not r["new_in_round"] for r in case_rows),
    "year_cases_missing": missing, "year_results": case_rows,
    "unsubmitted_year_cases": unsubmitted_cases, "submitted_unfinished_year_cases": unfinished_cases,
    "execution_unresolved_year_cases": unresolved_cases,
    "native_year_passes": passes, "followups": followups,
    "old_gate_completed_case_counts": dict(counts), "old_gate_native_passing_case_counts": dict(passing_counts),
    "pending_ids": sorted(set(pending)), "unobserved_ids": sorted(set(unknown)),
    "succeeded_uncollected": sorted(set(uncollected)), "failed_run_attempts": sorted(set(failed)),
    "admission_rejections": admission_rejected, "factor_source_exact_comparisons": comparisons,
    "note": "Saved MCP evidence only; no live polling by this renderer. Historical native capital10m probes, not certified100k or unseen out-of-sample results."}
if not missing and not any((pending, unknown, uncollected)) and not any(f["status"] == "required" for f in followups):
    state["status"] = "finite_audit_account_phase_complete"
elif not unsubmitted_cases and not unfinished_cases and not any((pending, unknown, uncollected)) and not any(f['status'] == 'required' for f in followups):
    state['status'] = 'finite_audit_executable_phase_complete_with_unresolved'
(ROOT / "round28-execution-state.json").write_text(dump(state))
num = lambda x: "空" if x is None else f"{x:.3f}"
pct = lambda x: "空" if x is None else f"{x:.2%}"
labels = {"old_gate_pass": "原因子门槛通过", "only_ic_fails": "仅IC条件未过",
    "q5_or_spread_also_fails": "最高组/配对差也未过", "metric_unavailable_or_low_coverage": "指标空值/覆盖不足",
    "no_same_year_factor": "冻结时缺少同年度因子"}
lines = ["# 既有定义的统一账户覆盖审计", "", "更新：" + state["updated_at"], "",
    "正Rank IC不是TopN多头盈利的必要条件。此次按全部既有提交冻结有限清单，"
    "统一检查固定账户参数；IC、最高组与配对差的正负只用于对照分类。"
    "[方法审查](ROUND28_METHOD_REVIEW.md)、[冻结清单与协议](round28-plan.json)、"
    "[独立反例核对](round28-gate-proof.json)。", "",
    f"清单包含{len(definitions)}个公式/行业处理定义、96个公式文本、218个一年期案例。"
    "冻结时71个可复用、143个需要补测，效率变化原式和等价式的4个案例保留为资源问题未解决。"
    "清单包含原候选、对照、组合及行业变体，并不代表109个独立经济家族。", "",
    "固定TOP3000、2025-09-10至2026-09-09，每个定义10/20只、每20个交易日调仓。"
    "全部沿用原公式和行业处理。原生本金1000万元；10万元、20%回撤仍需独立账户验证，不能按本金比例缩放。", "",
    f"目前完成{len(case_rows)}/218个固定案例，其中复用{state['reused_year_results']}、新完成{state['new_year_results']}；"
    f"全年Sharpe>1.2且回撤≤20%的案例{len(passes)}个。", "",
    f"剩余案例分别为：尚未提交{len(unsubmitted_cases)}，已提交但尚未收齐结果{len(unfinished_cases)}，"
    f"执行问题未解决{len(unresolved_cases)}。这些都不计作经济失败。", "",
    "|原筛选类别|已完成账户案例|原生全年达标|",
    "|---|---:|---:|"]
for category in ("old_gate_pass", "only_ic_fails", "q5_or_spread_also_fails", "metric_unavailable_or_low_coverage"):
    lines.append(f"|{labels[category]}|{counts[category]}|{passing_counts[category]}|")
if state['status'] == 'finite_audit_executable_phase_complete_with_unresolved':
    lines += ["", "固定清单的可执行部分已收齐，当前没有运行中或待采集任务。"
        "资源未解决案例继续保留；既包括实际失败，也包括按停止规则未派发的同定义账户。"
        "不在执行条件未变时重试，也不把这部分当作经济负结果。"]
lines += ["", "上表按本年度实际因子统计分类；“冻结时缺少年度因子”的定义在补测后归入相应类别。"
    "尚未完成的部分不能当作负结果，分批早期通过率不代表完整清单。", "",
    "来源列保留最早实验的原始名称。本次全部为一年期，实际持仓与调仓间隔在独立列中显示。", "",
    "|定义|历史来源名称|行业处理|本次持仓/调仓|累计净收益|最大回撤|Sharpe|旧门槛分类|原生全年通过|",
    "|---|---|---|---|---:|---:|---:|---|---|"]
for row in case_rows:
    lines.append(f"|[{row['definition_key']}](https://thesistrace.com/research-runs/{row['run_id']})|{row['source_name']}|"
        f"{row['neutralization']}|{row['holdings_count']}/20|{pct(row['net_return'])}|{pct(row['maximum_drawdown'])}|"
        f"{num(row['sharpe'])}|{labels[row['old_gate']['category']]}|{'是' if row['native_year_pass'] else '否'}|")
if (ROOT / 'round28-nav-audits.json').exists():
    nav_audits = read(ROOT / 'round28-nav-audits.json')
    lines += ["", f"本轮已有{len(nav_audits)}个完整净值路径用50位Decimal独立核对。"
        "每242个净值点使用241个相邻收益区间，不额外添加零收益。"
        "[净值、回撤、Sharpe与费用复算](round28-nav-audits.json)。"]
if (ROOT / 'ROUND28_ACCOUNT_DIAGNOSTICS.md').exists():
    lines += ["", "[正Sharpe与负累计收益的账户复核](ROUND28_ACCOUNT_DIAGNOSTICS.md)。"]
if (ROOT / 'ROUND28_SWITCH_PROOF.md').exists():
    lines += ["", "[三组个股状态切换的固定日期独立评分复算](ROUND28_SWITCH_PROOF.md)。"]
if (ROOT / 'ROUND28_INVENTORY_REVIEW.md').exists():
    lines += ["", "[129份来源、71个精确复用案例及segment2检查点的独立清单核对](ROUND28_INVENTORY_REVIEW.md)。"]
if (ROOT / 'ROUND28_SCALE_PROOF.md').exists():
    lines += ["", "[非流动性正比例变体的完整公开账户路径比较](ROUND28_SCALE_PROOF.md)。"]
if (ROOT / 'ROUND28_SEGMENT3_DIAGNOSTICS.md').exists():
    lines += ["", "[市场切换的固定频率对照、接近门槛的案例与长回看执行边界](ROUND28_SEGMENT3_DIAGNOSTICS.md)。"]
if (ROOT / 'ROUND28_SEGMENT3_REVIEW.md').exists():
    lines += ["", "[第三段原始证据与五条净值的独立复核](ROUND28_SEGMENT3_REVIEW.md)发现一处比较范围歧义，已修正并复查。"]
if admission_rejected:
    lines += ["", f"本轮另有{len(admission_rejected)}次提交前准入拒绝，这些被拒绝的请求未创建回测；与随后另行接受的任务和运行失败分别记录。"
        "[逐项审查与保留原输入的恢复安排](round28-admission-resolutions.json)。"]
if (ROOT / 'product-audit/ROUND28_METRIC_HELP_AUDIT.md').exists():
    lines += ["", "[策略首屏与Sharpe、回撤、费用帮助的四步走查](product-audit/ROUND28_METRIC_HELP_AUDIT.md)。"]
lines += ["", "全年实际账户通过，才按原持仓/调仓参数跟进固定三年、近期季度及完整净值复算。"
    "季度重新建仓与全年账户截取分别报告。以上历史区间已反复参与研究，不能称作未见样本外；"
    "此审计也未执行多重检验校正或证明未来收益。", "",
    "原轮次按各自协议关闭，本轮统一审计不改写旧结论，也不为某个结果较好的公式单独放宽条件。"
    "同公式、日期、数据、参数与计算契约的已完成结果复用；只有汇总值相同的不同公式不自动合并。", "",
    f"活跃或尚未观测任务：{len(state['pending_ids'])}；成功待采集：{len(state['succeeded_uncollected'])}；"
    f"本轮失败任务：{len(state['failed_run_attempts'])}。"]
(ROOT / "ROUND28_RESULTS.md").write_text("\n".join(lines) + "\n")
print(dump({k: state[k] for k in ("status", "fixed_definition_count", "fixed_year_cases", "collected_year_cases",
    "new_year_results", "reused_year_results", "old_gate_completed_case_counts",
    "old_gate_native_passing_case_counts", "pending_ids", "unobserved_ids", "succeeded_uncollected", "failed_run_attempts")}))
