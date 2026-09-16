"""Build empirical search tables from immutable MCP responses; stdlib only.

Run: uv run --no-project .scratch/top3000-sharpe-search-20260910/analyze.py
"""
import csv
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RECENT_WINDOWS = {"recent_3y": "2023-09-11", "recent_1y": "2025-09-10", "2026_YTD": "2026-01-05"}


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def stats(returns):
    if len(returns) < 2:
        return {}
    sd = statistics.stdev(returns)
    nav = peak = 1.0
    mdd = 0.0
    for value in returns:
        assert math.isfinite(value) and value > -1
        nav *= 1 + value
        peak = max(peak, nav)
        mdd = max(mdd, 1 - nav / peak)
    return {
        "sessions": len(returns),
        "return": nav - 1,
        "cagr": nav ** (252 / len(returns)) - 1,
        "sharpe": statistics.mean(returns) / sd * math.sqrt(252) if sd else None,
        "volatility": sd * math.sqrt(252),
        "max_drawdown": mdd,
    }


def fmt(value, percent=False):
    if value is None:
        return "—"
    return f"{value:.1%}" if percent else f"{value:.3f}"


def main():
    strategies, factors, audits, periods, recent = [], [], [], [], []
    submissions = [json.loads(path.read_text()) for path in (ROOT / "submissions").glob("*.json")]
    submissions = [row for row in submissions if row.get("response", {}).get("outcome") == "accepted"]
    submitted_single_ids = {row["response"]["run_id"] for row in submissions if "run_id" in row["response"]}
    submitted_batch_ids = {row['response']['batch_id'] for row in submissions if 'batch_id' in row['response']}
    records = sorted((ROOT / "results").glob("*.json"))
    for path in records:
        record = json.loads(path.read_text())
        run = record["run"]
        spec = run["input"]
        common = {"run_id": run["id"], "name": run["name"], "formula": spec["formula"],
                  "start": spec["start_date"], "end": spec["end_date"],
                  "universe": spec["universe"], "neutralization": spec["neutralization"],
                  "status": run["status"]}
        if "summary" in record:
            summary = record["summary"]
            m = summary["metrics"]
            comparison = summary["comparison"]
            cmp = comparison.get("metrics", {})
            strategies.append({**common, "initial_cash_cny": float(summary["initial_cash_cny"]),
                "matches_100k_capital": float(summary["initial_cash_cny"]) == 100000,
                "within_20pct_drawdown": m["maximum_drawdown"]["value"] <= 0.2,
                "holdings": spec["holdings_count"],
                "rebalance": spec["rebalance_every_sessions"], "sharpe": m["sharpe"],
                "above_1_2": m["sharpe"] is not None and m["sharpe"] > 1.2,
                "net_cagr": m["net_cagr"], "net_return": m["net_cumulative_return"],
                "max_drawdown": m["maximum_drawdown"]["value"],
                "annualized_excess": cmp.get("annualized_excess_return"),
                "benchmark_cagr": cmp.get("benchmark_cagr"),
                "cost_drag": m["transaction_costs"]["return_drag"],
                "turnover": m["turnover"]["annualized"],
                "mean_cash_ratio": m["cash_ratio"]["mean"],
                "mean_holdings": m["holdings_count"]["mean"],
                "max_name_weight": m["maximum_single_name_weight"]["period_maximum"]["value"]})
        if "factor" in record:
            row = dict(common)
            for key, item in record["factor"]["factor"]["horizons"].items():
                h = item["horizon"]
                s = item["summary"]
                row.update({f"rank_ic_{h}": s["rank_ic"]["mean"],
                            f"rank_icir_{h}": s["rank_ic"]["icir"],
                            f"ic_{h}": s["ic"]["mean"],
                            f"long_short_{h}": s["top_bottom_return"],
                            f"valid_sessions_{h}": item["coverage"]["rank_ic_valid_session_count"]})
            factors.append(row)
        observation_path = ROOT / "observations" / f"{run['id']}.json"
        if observation_path.exists():
            data = json.loads(observation_path.read_text())
            observations = data["items"]
            assert data.get("next_cursor") is None, "Incomplete observations pagination"
            assert len(observations) > 2
            sessions = [x["session"] for x in observations]
            assert sessions == sorted(set(sessions)), "Duplicate or unordered sessions"
            navs = [float(x["net_nav"]) for x in observations]
            assert all(math.isfinite(x) and x > 0 for x in navs)
            daily = [(sessions[i], navs[i] / navs[i-1] - 1) for i in range(1, len(navs))]
            observed = stats([x[1] for x in daily])
            reported = record["summary"]["metrics"]
            error = abs(observed["sharpe"] - reported["sharpe"])
            dd_error = abs(observed["max_drawdown"] - reported["maximum_drawdown"]["value"])
            assert error < 1e-8, (run["id"], "Sharpe mismatch", error)
            assert dd_error < 1e-8, (run["id"], "Drawdown mismatch", dd_error)
            audits.append({"run_id": run["id"], "observations": len(observations),
                           "first_session": sessions[0], "last_session": sessions[-1],
                           "recomputed_sharpe": observed["sharpe"], "sharpe_error": error,
                           "drawdown_error": dd_error})
            bins = defaultdict(list)
            for session, value in daily:
                bins[session[:4]].append(value)
                bins["2018-2022" if session < "2023-01-01" else "2023-latest"].append(value)
            for period, values in sorted(bins.items()):
                periods.append({"run_id": run["id"], "name": run["name"], "period": period,
                                **stats(values)})
            for window, start in RECENT_WINDOWS.items():
                if sessions[0] <= start < sessions[-1]:
                    values = [value for session, value in daily if session > start]
                    recent.append({"run_id": run["id"], "name": run["name"], "window": window,
                                   "start": start, "end": sessions[-1], "evidence": "existing_path_slice",
                                   **stats(values)})
            for length in (63, 126, 252):
                if len(daily) >= length:
                    recent.append({"run_id": run["id"], "name": run["name"], "window": f"last_{length}_sessions",
                                   "start": sessions[-length-1], "end": sessions[-1], "evidence": "existing_path_slice",
                                   **stats([value for _, value in daily[-length:]])})
    strategies.sort(key=lambda r: r["sharpe"] if r["sharpe"] is not None else -1e9, reverse=True)
    factors.sort(key=lambda r: r.get("rank_ic_5") or 0, reverse=True)
    distinct_factors = {}
    for row in factors:
        key = (row["formula"], row["start"], row["end"], row["universe"], row["neutralization"])
        distinct_factors.setdefault(key, row)
    factor_rows = list(distinct_factors.values())
    write_csv(ROOT / "strategies.csv", strategies)
    small_prescreen = [r for r in strategies if r["name"].startswith(("QS6 prescreen ", "QS8 "))]
    small_prescreen.sort(key=lambda r: r["net_cagr"] if r["net_cagr"] is not None else -1e9, reverse=True)
    write_csv(ROOT / "small-account-prescreen.csv", small_prescreen)
    write_csv(ROOT / "factors.csv", factors)
    write_csv(ROOT / "nav-audit.csv", audits)
    write_csv(ROOT / "periods.csv", periods)
    write_csv(ROOT / "recent-path-diagnostics.csv", recent)
    winners = [r for r in strategies if r["above_1_2"]]
    exact_control_winners = [r for r in winners if r['name'].startswith('QS16 1y common_valid_amount_cash ')]
    noncontrol_winners = [r for r in winners if r not in exact_control_winners]
    active = []
    observed_batch_ids = set()
    for path in (ROOT / "batches").glob("*.json"):
        b = json.loads(path.read_text())
        observed_batch_ids.add(b['id'])
        if b["status"] in ("queued", "running", "cancelling"):
            active.append((b["id"], b["status"], b["progress"]))
    active.extend((bid, 'accepted_not_yet_polled', {}) for bid in sorted(submitted_batch_ids - observed_batch_ids))
    active_runs = []
    for path in (ROOT / "runs").glob("*.json"):
        run = json.loads(path.read_text())
        if run["id"] in submitted_single_ids and run["status"] in ("queued", "running", "cancelling"):
            active_runs.append((run["id"], run["status"], run["name"]))
    submitted_factor_count = submitted_strategy_count = 0
    submitted_factor_cases = set()
    for submission in submissions:
        inp = submission["input"]
        submitted_factor_count += len(inp.get("factors", [])) + (inp.get("research_kind") == "factor_evaluation")
        submitted_strategy_count += len(inp.get("strategies", [])) + (inp.get("research_kind") == "strategy_backtest")
        factor_inputs = inp.get("factors", []) if "batch_kind" in inp else ([inp] if inp.get("research_kind") == "factor_evaluation" else [])
        for factor in factor_inputs:
            submitted_factor_cases.add((factor["formula"], inp["start_date"], inp["end_date"], inp["universe"], inp["neutralization"]))
    offline_path = ROOT / "capital-replay-audit.json"
    offline_small_count = sum(r['capital'] == 100000 for r in json.loads(offline_path.read_text())) if offline_path.exists() else 0
    round28_state = json.loads((ROOT / 'round28-execution-state.json').read_text())
    round28_summary = (
        f"[既有定义统一账户审计](ROUND28_RESULTS.md)：固定109个定义、218个H10/H20/R20年度案例；"
        f"已完成{round28_state['collected_year_cases']}个，其中复用{round28_state['reused_year_results']}个，"
        f"执行问题未解决{len(round28_state['execution_unresolved_year_cases'])}个。"
        f"全年Sharpe>1.2且回撤≤20%的固定案例{len(round28_state['native_year_passes'])}个。"
        "相关性与分位收益只用于分类；[方法审查](ROUND28_METHOD_REVIEW.md)与[独立清单核对](ROUND28_INVENTORY_REVIEW.md)保留选择和复用证据。"
        "只检验这组固定持仓/频率，不能推断所有参数无效，也不表示发现新家族或取得未见样本外证据。")
    lines = ["# TOP3000 策略与因子持续研究", "",
             f"更新：{datetime.now(timezone.utc).isoformat()}", "",
             "最新已固定数据日：2026-09-09；终值为该日开盘估值。"
             "研究同时覆盖2018年起的长区间、2023年起的对照，以及近3年、近1年和2026年至今。", "",
             f"已接受 {submitted_factor_count} 次因子评估任务（{len(submitted_factor_cases)} 个公式/区间/中性化案例，包含失败后恢复提交）、{submitted_strategy_count} 个策略回测。"
             f"已采集 {len(strategies)} 个策略结果，{len(factor_rows)} 个不同公式/区间/中性化的因子结果（含策略关联因子）。"
             f"策略 Sharpe > 1.2：{len(winners)} 个参数组合，"
             f"{len(set(r['formula'] for r in winners))} 个不同公式文本。"
             f"其中{len(exact_control_winners)}项为已证明观察路径重复的有效样本对照；排除后为{len(noncontrol_winners)}个区间/参数案例、{len(set(r['formula'] for r in noncontrol_winners))}个公式文本，仍不代表独立经济家族。", "",
             "Sharpe 为平台扣除交易费用后的净收益日序列年化值；阈值严格大于 1.2。"
             "各参数变体并非独立策略家族。全历史已用于探索，年度和近期切片只能检验时间稳定性，不能称作未接触的样本外。", "",
             "QS4为个股评分切换；QS10/11/12/15的门控为排除自身后的市场宽度筛选，候选为空时按原调仓日退出；QS16按该宽度在低成交额与低波动之间切换评分。"
             "两者只用当时已知信息，次日开盘执行；均不是多个策略之间的动态组合分配，公式本身经过后验研究筛选。", "",
             "当前用户约束：本金10万元，最大回撤目标20%。平台初始资金固定1000万元，"
             f"本表属于线上大本金研究。独立10万元模型已用本地真实行情完成{offline_small_count}个情景，数据止于2026-08-27；"
             "两类结果不能混为同一本金或日期，也不能线性缩放。"
             "参见 [10万元回放](CAPITAL_REPLAY.md)、[市场择时验证](MARKET_TIMING.md)、[两种评分切换](MARKET_SWITCH.md)、[调仓邻近检验](SWITCH_NEIGHBORS.md) 与 [产品问题记录](product-audit/REPORT.md)。", "",
             "新增研究：[经营效率与交易活动稳定性](ROUND18_RESULTS.md)、[既有因子转实际策略](ROUND19_RESULTS.md)、[自回归与历史风险稳定性](ROUND20_RESULTS.md)。各轮保留预声明、负结果、匹配对照与未完成任务；短期通过不等于10万元账户已通过全部验证。", "",
             "后续核查：[财务策略执行与资源限制](ROUND21_RESULTS.md)、[过线案例的日收益相关性](CANDIDATE_DEPENDENCE.md)、[新资料去重与排除理由](ROUND21_SOURCES.md)。收益相关性按相同起点和本金比较；没有将候选加权为新组合，也没有把失败任务计为策略负收益。", "",
             "继续补齐：[九项因子的18个实际策略](ROUND22_RESULTS.md)。它们均未通过全年Sharpe与回撤条件，不再继续调参。另有一个[赢家条件内的连续性检验](ROUND23_RESULTS.md)，保留[原始资料](ROUND22_SOURCES.md)与[候选及匹配对照的预声明](round23-plan.json)。", "",
             "后续执行：[经营效率的等价恢复](ROUND24_RESULTS.md)仍受资源限制；[日收益总偏度检验](ROUND25_RESULTS.md)在已有反彩票家族内比较三阶矩、MAX与低波动，不能只凭公式不同宣布新独立Alpha。", "",
             "最新覆盖：[原始信号的一年期补测](ROUND26_RESULTS.md)按完整20项清单补齐16个旧定义；[21/200日均价比](ROUND27_RESULTS.md)与相同历史覆盖的动量、价格/长均价比较。[来源核对](ROUND26_SOURCES.md)保留论文版本、交易对象和可表达性边界。", "",
             round28_summary, "",
             "调仓敏感性已出现反证：QS17四个预先固定邻居均未同时通过全年和季度；例如20只/9日季度Sharpe3.300，全年只有0.233。表中短期高值是已筛选历史区间的结果，不表示推荐10万元实盘。", "",
             "## 按回测区间统计", "",
             "|区间|已采集策略数|Sharpe > 1.2|最高 Sharpe|",
             "|---|---:|---:|---:|"]
    by_window = defaultdict(list)
    for row in strategies:
        by_window[(row["start"], row["end"])].append(row)
    for (start, end), rows in sorted(by_window.items()):
        valid = [row["sharpe"] for row in rows if row["sharpe"] is not None]
        lines.append(f"|{start} → {end}|{len(rows)}|{sum(row['above_1_2'] for row in rows)}|{fmt(max(valid) if valid else None)}|")
    lines += ["", "## 策略结果（各行日期不同，按 Sharpe 排序仅供检索）", "",
             "|名称|区间起点|中性化|持仓/调仓|Sharpe|净年化|最大回撤|年化超额|Run|",
             "|---|---|---|---|---:|---:|---:|---:|---|"]
    for r in strategies:
        lines.append(f"|{r['name']}|{r['start']}|{r['neutralization']}|{r['holdings']}/{r['rebalance']}|"
                     f"{fmt(r['sharpe'])}|{fmt(r['net_cagr'], True)}|{fmt(r['max_drawdown'], True)}|"
                     f"{fmt(r['annualized_excess'], True)}|`{r['run_id']}`|")
    lines += ["", "## 因子筛选", "", "因子 Rank IC 不是 Sharpe；多空分组收益也未计入交易成本。", "",
              "各行日期不同，排序仅供检索，不将短窗口与多年样本视为同一对照。", "",
              "|名称|区间起点|中性化|1日 Rank IC|5日 Rank IC|20日 Rank IC|5日多空收益|",
              "|---|---|---|---:|---:|---:|---:|"]
    for r in factor_rows:
        lines.append(f"|{r['name']}|{r['start']}|{r['neutralization']}|{fmt(r.get('rank_ic_1'))}|"
                     f"{fmt(r.get('rank_ic_5'))}|{fmt(r.get('rank_ic_20'))}|{fmt(r.get('long_short_5'),True)}|")
    lines += ["", "## 近期切片诊断", "",
              "以下沿用原回测持仓、资金和调仓相位，只用于发现时间适应性。"
              "与近期重新建仓的独立回测不同，不计入上面的达标数量。63/126交易日值样本较短。", "",
              "|原始策略|窗口|Sharpe|区间收益|最大回撤|", "|---|---|---:|---:|---:|"]
    for row in recent:
        if row["window"] in RECENT_WINDOWS:
            lines.append(f"|{row['name']}|{row['window']}|{fmt(row.get('sharpe'))}|{fmt(row.get('return'),True)}|{fmt(row.get('max_drawdown'),True)}|")
    lines += ["", "## 可复核证据", "",
              "- `submissions/`：每次提交的完整公式、日期、参数、request_id 与 batch_id。",
              "- `batches/`：最近一次读取的服务端状态；失败与未完成项保留。",
              "- `results/`：MCP 原始 Run / Factor / Strategy Summary。",
              "- `observations/`：完整分页净值数据；`nav-audit.csv` 为独立 Sharpe / 回撤复算。",
              "- `periods.csv`：同一策略路径的年度与时间段表现，2026 年为截至最新日。",
              "- `recent-path-diagnostics.csv`：近3年/1年/YTD与63/126/252交易日路径切片。",
              "- `regime-plan.json`：状态切换公式、预先选定窗口和适用边界。",
              "- `research-contract.md`：当前模型假设、代码和原始文献。", "",
              f"独立净值复算：{len(audits)} 个策略。", "", "## 仍在运行", ""]
    lines.extend(f"- `{bid}`：{status}，{progress}" for bid, status, progress in active)
    lines.extend(f"- `{rid}`：{status}，{name}" for rid, status, name in active_runs)
    (ROOT / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"submitted_factors": submitted_factor_count, "submitted_strategies": submitted_strategy_count,
                      "strategies": len(strategies), "factor_results": len(factor_rows),
                      "above_1_2": len(winners), "distinct_formulas": len(set(r['formula'] for r in winners)),
                      "nav_audited": len(audits), "active_batches": len(active),
                      "active_single_runs": len(active_runs)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
