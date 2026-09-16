"""Same-start daily-return dependence among existing native Sharpe passes.

No new backtests, portfolio combinations, weight fitting or independent-family count.
"""
import csv
import itertools
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXACT_CONTROLS = {'run_7297da0535ff4eacbb47', 'run_1b505fb2143246efb3e6'}
records = [json.loads(p.read_text()) for p in (ROOT / 'results').glob('*.json')]
selected = [r for r in records if 'summary' in r and r['summary']['metrics']['sharpe'] is not None and r['summary']['metrics']['sharpe'] > 1.2 and r['run']['id'] not in EXACT_CONTROLS]
groups = defaultdict(list)
missing = []
generation_contracts = set()
for r in selected:
    rid = r['run']['id']
    path = ROOT / 'observations' / (rid + '.json')
    if not path.exists():
        missing.append(rid)
        continue
    d = json.loads(path.read_text())
    assert d['next_cursor'] is None
    days = d['items']
    assert [x['session'] for x in days] == sorted({x['session'] for x in days})
    nav = [float(x['net_nav']) for x in days]
    returns = {days[i]['session']: nav[i] / nav[i - 1] - 1 for i in range(1, len(nav))}
    assert all(math.isfinite(x) and x > -1 for x in returns.values())
    point = statistics.mean(returns.values()) / statistics.stdev(returns.values()) * math.sqrt(252)
    assert abs(point - r['summary']['metrics']['sharpe']) < 1e-8
    inp = r['run']['input']
    prov = r['provenance']
    assert prov['authoring_input'] == inp
    generation_contracts.add((prov['data']['generation_id'], prov['data']['data_through_session'],
        json.dumps(prov['execution']['semantic_versions'], sort_keys=True),
        prov['execution']['calculation_contracts']['numeric_execution_contract']))
    assert inp['universe'] == 'top3000' and inp['neutralization'] == 'none'
    group = (inp['start_date'], inp['end_date'], r['summary']['initial_cash_cny'])
    groups[group].append((r, returns))

def correlation(xs, ys):
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    x, y = [v - mx for v in xs], [v - my for v in ys]
    den = math.sqrt(math.fsum(v * v for v in x) * math.fsum(v * v for v in y))
    return math.fsum(a * b for a, b in zip(x, y)) / den if den else None

assert len(generation_contracts) == 1, 'Do not compare silently different frozen computation or data versions'
pairs = []
for (start, end, capital), group in sorted(groups.items()):
    for (left, lr), (right, rr) in itertools.combinations(sorted(group, key=lambda x: x[0]['run']['name']), 2):
        assert lr.keys() == rr.keys(), 'Do not silently pair unequal date coverage'
        dates = sorted(lr)
        rho = correlation([lr[d] for d in dates], [rr[d] for d in dates])
        pairs.append({'start': start, 'end': end, 'initial_cash_cny': capital, 'daily_returns': len(dates),
                      'left_run': left['run']['id'], 'left_name': left['run']['name'],
                      'right_run': right['run']['id'], 'right_name': right['run']['name'],
                      'pearson_daily_return_correlation': rho,
                      'same_literal_formula': left['run']['input']['formula'] == right['run']['input']['formula']})
with (ROOT / 'candidate-dependence.csv').open('w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=list(pairs[0]))
    writer.writeheader(); writer.writerows(pairs)
payload = {'observed_at': datetime.now(timezone.utc).isoformat(), 'selected_nonduplicate_case_count': len(selected),
           'verified_generation_contracts': sorted(generation_contracts),
           'matched_observation_cases': sum(len(v) for v in groups.values()), 'missing_observations': missing,
           'pair_count': len(pairs), 'pairs': pairs,
           'limits': 'Post-selection descriptive Pearson correlation within exactly equal start/end/capital. Different start cohorts are not mixed. Same generation already verified by source Results; no new return model, combination portfolio, future diversification claim or formal count of independent hypotheses.'}
(ROOT / 'candidate-dependence.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
lines = ['# 高Sharpe案例之间的账户收益相关性', '', '更新：' + payload['observed_at'], '',
    '只比较相同起止日期、相同原生本金的完整日净收益。先排除两项已证明逐日观察重复的现金对照，再读取已完成的净值；不把不同起始持仓的账户拼接，不组合资金或拟合权重。', '',
    f"原先14个Sharpe>1.2案例去掉两项重复对照后为{len(selected)}项；其中{payload['matched_observation_cases']}项有完整净值，缺失{len(missing)}项。按区间分别比较，共{len(pairs)}对。单独的三年案例没有同起点的过线对照。", '',
    '|区间起点|左侧案例|右侧案例|净日收益数|Pearson相关性|同一公式文本|', '|---|---|---|---:|---:|---|']
for p in sorted(pairs, key=lambda p: (p['start'], -p['pearson_daily_return_correlation'])):
    lines.append(f"|{p['start']}|[{p['left_name']}](https://thesistrace.com/research-runs/{p['left_run']})|[{p['right_name']}](https://thesistrace.com/research-runs/{p['right_run']})|{p['daily_returns']}|{p['pearson_daily_return_correlation']:.3f}|{'是' if p['same_literal_formula'] else '否'}|")
lines += ['', '这些都是从已搜索历史中挑出的案例，相关性只是该段账户收益的描述。高相关提示不能简单把策略数量当作分散程度；低相关也不证明经济机制独立、未来相关性稳定或合并后的10万元账户可执行。季度样本尤其短，不能从它反推出全年关系。', '',
    '原始来源为每个Result和完整strategy_observations；所有输入净值重算Sharpe已与对应摘要核对。当前结果没有新增策略或新的Sharpe>1.2案例。[完整配对数据](candidate-dependence.json)。', '']
(ROOT / 'CANDIDATE_DEPENDENCE.md').write_text('\n'.join(lines) + '\n')
print(json.dumps({'cases': len(selected), 'missing': missing, 'pairs': len(pairs), 'by_start': {start: {'min': min(x['pearson_daily_return_correlation'] for x in pairs if x['start'] == start), 'max': max(x['pearson_daily_return_correlation'] for x in pairs if x['start'] == start)} for start in sorted({x['start'] for x in pairs})}}))
