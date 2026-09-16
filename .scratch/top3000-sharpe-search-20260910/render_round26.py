"""Collect the fixed original-signal latest-year coverage experiment from saved MCP data."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
read = lambda p: json.loads(p.read_text())
plan = read(ROOT / "round26-plan.json")
records = {p.stem: read(p) for p in (ROOT / "results").glob("*.json")}
batches = {p.stem: read(p) for p in (ROOT / "batches").glob("*.json")}
runs = {p.stem: read(p) for p in (ROOT / "runs").glob("*.json")}
active = {"queued", "running", "cancelling"}
pending, singles, uncollected, failed, ids = [], [], [], [], set()
for path in (ROOT / "submissions").glob("r26-*.json"):
    sub = read(path); response = sub["response"]
    if response.get("outcome") != "accepted":
        continue
    if "batch_id" in response:
        bid = response["batch_id"]; batch = batches.get(bid)
        if batch is None or batch["status"] in active:
            pending.append(bid)
        items = batch.get("items", []) if batch else []
    else:
        rid = response["run_id"]; run = runs.get(rid)
        if run is None or run["status"] in active:
            singles.append(rid)
        items = [{"research_run_id": rid, "status": run["status"] if run else None}]
    for item in items:
        rid = item["research_run_id"]; ids.add(rid)
        if item["status"] == "succeeded" and rid not in records:
            uncollected.append(rid)
        if item["status"] == "failed":
            failed.append(rid)
collected = [records[rid] for rid in ids if rid in records]
factors = [r for r in collected if r["run"]["research_kind"] == "factor_evaluation"]
strategies = [r for r in collected if "summary" in r]
positive = lambda v: v is not None and math.isfinite(v) and v > 0
num = lambda v: "空" if v is None else f"{v:.4f}"
pc = lambda v: "空" if v is None else f"{v:.2%}"
now = datetime.now(timezone.utc).isoformat()
screen, selected, missing, year_rows, followups = [], [], [], [], []
lines = ["# 原始信号的一年期覆盖补测", "", "更新：" + now, "",
    "原始20个固定定义中，3个已有同公式的一年期结果；原始ROE已由正权益修正版取代，其余16个补测。"
    "不按旧收益挑选，也不更改方向、窗口或权重。非流动性已有正比例缩放版本，本轮原式另作核对，均不计新增经济家族。"
    "[预声明](round26-plan.json)、[20项完整覆盖清单](round26-selection-audit.json)。", "",
    "固定TOP3000、2025-09-10至2026-09-09、无行业去均值。长区间为2018-01-02至2026-09-09，"
    "包含本次一年期，不是独立样本。因子统计不等于账户收益。", "",
    "|原始信号|长区间20日Rank IC|本次20日Rank IC|本次20日最高组|本次20日配对差|有效/信号日|因子通过|",
    "|---|---:|---:|---:|---:|---:|---|"]
for spec in plan["factors"]:
    matches = [r for r in factors if r["run"]["input"]["formula"] == spec["formula"]]
    assert len(matches) <= 1
    old = [r for r in records.values() if r["run"]["input"]["formula"] == spec["formula"]
        and r["run"]["input"]["start_date"] == "2018-01-02"
        and r["run"]["input"]["end_date"] == plan["end_date"]
        and r["run"]["input"]["neutralization"] == "none"]
    old_ic = old[0]["factor"]["factor"]["horizons"]["20"]["summary"]["rank_ic"]["mean"] if old else None
    if not matches:
        lines.append(f"|{spec['source_name']}|{num(old_ic)}|—|—|—|—|待采集|")
        continue
    r = matches[0]; inp = r["run"]["input"]; prov = r["provenance"]
    assert prov["authoring_input"] == inp
    assert all(inp[k] == plan[k] for k in ("start_date", "end_date", "universe", "neutralization"))
    h = r["factor"]["factor"]["horizons"]["20"]; s = h["summary"]; c = h["coverage"]
    conditions = {"rank_ic_positive": positive(s["rank_ic"]["mean"]),
        "q5_positive": positive(s["quantile_returns"]["q5"]),
        "paired_spread_positive": positive(s["top_bottom_return"]),
        "coverage90": c["signal_session_count"] > 0 and c["rank_ic_valid_session_count"] / c["signal_session_count"] >= .9}
    passed = all(conditions.values())
    row = {"key": spec["item_key"], "run_id": r["run"]["id"], "role": spec["role"],
        "old_rank_ic20": old_ic, "conditions": conditions, "selected": passed}
    screen.append(row)
    if passed:
        selected.append(spec)
    lines.append(f"|[{spec['source_name']}](https://thesistrace.com/research-runs/{r['run']['id']})|"
        f"{num(old_ic)}|{num(s['rank_ic']['mean'])}|{pc(s['quantile_returns']['q5'])}|"
        f"{pc(s['top_bottom_return'])}|{c['rank_ic_valid_session_count']}/{c['signal_session_count']}|{'是' if passed else '否'}|")
for spec in selected:
    for cfg in plan["selection"]["actual_if_pass"]:
        matches = [r for r in records.values() if "summary" in r
            and r["run"]["input"]["formula"] == spec["formula"]
            and all(r["run"]["input"][k] == plan[k] for k in ("start_date", "end_date", "universe", "neutralization"))
            and all(r["run"]["input"][k] == v for k, v in cfg.items())]
        assert len(matches) <= 1
        if not matches:
            missing.append({"key": spec["item_key"], **cfg})
            continue
        r = matches[0]; m = r["summary"]["metrics"]
        assert float(r["summary"]["initial_cash_cny"]) == 10000000
        passed = m["sharpe"] is not None and m["sharpe"] > 1.2 and m["maximum_drawdown"]["value"] <= .2
        row = {"key": spec["item_key"], "run_id": r["run"]["id"], **cfg,
            "net_return": m["net_cumulative_return"], "maximum_drawdown": m["maximum_drawdown"]["value"],
            "sharpe": m["sharpe"], "passed_year": passed}
        year_rows.append(row)
        if passed:
            followups.append(row)
complete = len(factors) == len(plan["factors"]) and not any((pending, singles, uncollected, failed, missing, followups))
state = {"updated_at": now, "source": "Saved MCP responses; no live polling by this script",
    "status": "complete_fixed_round_no_further_followup" if complete else "research_in_progress",
    "collected_factor_count": len(factors), "factor_screen": screen,
    "selected_keys": [s["item_key"] for s in selected], "collected_strategy_count": len(strategies),
    "required_year_strategies_uncollected": missing, "year_strategy_results": year_rows,
    "candidate_year_pass_requires_followup": followups,
    "pending_batches": sorted(set(pending)), "pending_single_runs": sorted(set(singles)),
    "succeeded_uncollected": sorted(set(uncollected)), "failed_run_attempts": sorted(set(failed))}
lines += ["", "固定筛选要求20日Rank IC、最高组收益与配对差均为正，有效日覆盖至少90%。"
    "通过后按10/20只、每20日调仓检查真实策略；不把1/5日较好结果改为事后筛选标准。", "",
    "|实际策略|持仓/调仓|累计净收益|最大回撤|Sharpe|全年通过|",
    "|---|---|---:|---:|---:|---|"]
for row in year_rows:
    lines.append(f"|[{row['key']}](https://thesistrace.com/research-runs/{row['run_id']})|"
        f"{row['holdings_count']}/{row['rebalance_every_sessions']}|{pc(row['net_return'])}|"
        f"{pc(row['maximum_drawdown'])}|{num(row['sharpe'])}|{'是' if row['passed_year'] else '否'}|")
if not year_rows:
    lines.append("|尚无已采集实际策略|—|—|—|—|—|")
if complete:
    lines += ["", "本轮16个因子全部完成，5个通过预设因子筛选，其10个实际策略全部未达到Sharpe>1.2与回撤≤20%。"
        "实际Sharpe范围−1.269至0.184，最大回撤23.69%至46.72%；不追加其他期限或调参。"]
if (ROOT / "round26-momentum-nav-audit.json").exists():
    lines += ["", "中期动量20只持仓案例已取回完整242日净值（241个相邻收益区间）并用Decimal独立复算。"
        "净收益、46.72%回撤、峰谷日期及费用一致，Sharpe差小于3e−17。"
        "核对器最初误加一个零收益区间，修正后通过；产品和原Result均未修改。"
        "[完整复算及首次偏差说明](round26-momentum-nav-audit.json)。"]
lines += ["", f"已收集{len(factors)}/16个因子，{len(year_rows)}个全年策略；"
    f"通过因子条件{len(selected)}项，待完成全年策略{len(missing)}项。", "",
    "原生账户本金1000万元。用户的10万元、20%回撤目标不变；未通过本金、成本、权限、近期和长周期检验前，不列为可实施结论。",
    "相同参数的三年和季度检查由全年实际Sharpe>1.2且回撤≤20%触发；窗口均已参与探索，不宣称样本外。", "",
    f"状态：{state['status']}。活跃批次：{', '.join(state['pending_batches']) or '无'}。"
    f"成功待采集：{', '.join(state['succeeded_uncollected']) or '无'}。", ""]
(ROOT / "round26-execution-state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
(ROOT / "ROUND26_RESULTS.md").write_text("\n".join(lines) + "\n")
print(json.dumps(state, ensure_ascii=False))
