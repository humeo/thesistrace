"""Exploratory circular block resampling of already observed daily returns.

No future/out-of-sample claim; no correction for choosing these runs after search.
Run with uv run --no-project.
"""
import csv
import json
import math
import random
import statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNS = [
    "run_96384289b08844dca9dc",
    "run_f87508c0fc204af1b381",
    "run_072d4799de174a6dbb02",
    "run_e20c03fe0028468799de",
    "run_ec334d7e6ddd464f806e",
    "run_779d11c1a18f4eb4bff7",
    "run_31298510aab342a2a630",
]
REPS = 2000
BLOCKS = (5, 10, 20)
SEED = 20260910

def sharpe(xs):
    mu = statistics.fmean(xs)
    variance = math.fsum((x - mu) ** 2 for x in xs) / (len(xs) - 1)
    return mu * math.sqrt(252 / variance) if variance > 0 else None

def quantile(sorted_values, fraction):
    point = (len(sorted_values) - 1) * fraction
    lower = math.floor(point)
    upper = math.ceil(point)
    return sorted_values[lower] + (point - lower) * (sorted_values[upper] - sorted_values[lower])

def main():
    rows = []
    for run_index, run_id in enumerate(RUNS):
        result = json.loads((ROOT / "results" / f"{run_id}.json").read_text())
        observations = json.loads((ROOT / "observations" / f"{run_id}.json").read_text())
        assert observations["next_cursor"] is None
        days = observations["items"]
        sessions = [row["session"] for row in days]
        assert sessions == sorted(set(sessions))
        nav = [float(row["net_nav"]) for row in days]
        assert all(math.isfinite(x) and x > 0 for x in nav)
        returns = [b / a - 1 for a, b in zip(nav, nav[1:])]
        point = sharpe(returns)
        assert abs(point - result["summary"]["metrics"]["sharpe"]) < 1e-8
        n = len(returns)
        for block in BLOCKS:
            rng = random.Random(SEED + run_index * 100 + block)
            samples = []
            for _ in range(REPS):
                xs = []
                while len(xs) < n:
                    start = rng.randrange(n)
                    xs.extend(returns[(start + offset) % n] for offset in range(block))
                value = sharpe(xs[:n])
                if value is not None and math.isfinite(value):
                    samples.append(value)
            samples.sort()
            assert len(samples) > REPS * 0.99
            rows.append({
                "run_id": run_id,
                "name": result["run"]["name"],
                "start": sessions[0],
                "end": sessions[-1],
                "actual_initial_cash_cny": float(result["summary"]["initial_cash_cny"]),
                "daily_returns": n,
                "point_sharpe": point,
                "block_sessions": block,
                "resamples": len(samples),
                "q025": quantile(samples, .025),
                "median": quantile(samples, .5),
                "q975": quantile(samples, .975),
                "bootstrap_fraction_above_1_2": sum(s > 1.2 for s in samples) / len(samples),
                "selection_bias_adjusted": False,
                "out_of_sample": False,
            })
    with (ROOT / "sharpe-resampling.csv").open("w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# 现有候选 Sharpe 的区块重采样诊断", "",
        f"更新：{datetime.now(timezone.utc).isoformat()}。固定随机种子{SEED}，每组{REPS}次。", "",
        "仅检查已观察到的净日收益，在保持5/10/20交易日短块内部顺序时，历史样本变化对Sharpe点估计的影响。",
        "这是循环区块重采样的经验分位范围，不是未来收益预测、不代表真实Sharpe超过门槛的概率，也不校正挑选赢家后的多重检验偏差。",
        "市场非平稳、短窗口仅几个独立块等限制仍存在。结果均来自平台固定1000万元，不能替代10万元重放。", "",
        "|Run|日收益数|块长|原Sharpe|重采样2.5%分位|重采样97.5%分位|", "|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(f"|{row['name']}|{row['daily_returns']}|{row['block_sessions']}|{row['point_sharpe']:.3f}|{row['q025']:.3f}|{row['q975']:.3f}|")
    lines += ["", "处理原则：保留原测得的Sharpe>1.2候选计数，但额外标记统计不确定性；不能把一次超过1.2直接解释为稳定达标。所有重采样前的点估计已与平台摘要核对至1e-8。", ""]
    (ROOT / "SHARPE_UNCERTAINTY.md").write_text("\n".join(lines))
    print(json.dumps(rows, ensure_ascii=False))

if __name__ == "__main__":
    main()
