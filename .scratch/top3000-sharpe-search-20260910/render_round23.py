"""Render fixed conditional-continuity screening from persisted MCP evidence."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ACTIVE = {'queued', 'running', 'cancelling'}
plan = json.loads((ROOT / 'round23-plan.json').read_text())
records = {p.stem: json.loads(p.read_text()) for p in (ROOT / 'results').glob('*.json')}
batches = {p.stem: json.loads(p.read_text()) for p in (ROOT / 'batches').glob('*.json')}
runs = {p.stem: json.loads(p.read_text()) for p in (ROOT / 'runs').glob('*.json')}
submissions = [json.loads(p.read_text()) for p in (ROOT / 'submissions').glob('r23-*.json')]
now = datetime.now(timezone.utc).isoformat()

def pc(value):
    return '空' if value is None else f'{value:.2%}'

def num(value):
    return '空' if value is None else f'{value:.4f}'

def positive(value):
    return value is not None and math.isfinite(value) and value > 0

pending, pending_single, uncollected, failed, accepted_ids = [], [], [], [], set()
for s in submissions:
    response = s['response']
    if response.get('outcome') != 'accepted':
        continue
    if 'batch_id' in response:
        bid = response['batch_id']; batch = batches.get(bid)
        if not batch or batch['status'] in ACTIVE:
            pending.append(bid)
        items = batch.get('items', []) if batch else []
    else:
        rid = response['run_id']; run = runs.get(rid)
        if not run or run['status'] in ACTIVE:
            pending_single.append(rid)
        items = [{'research_run_id': rid, 'status': run['status'] if run else None}]
    for item in items:
        rid = item['research_run_id']; accepted_ids.add(rid)
        if item['status'] == 'succeeded' and rid not in records:
            uncollected.append(rid)
        if item['status'] == 'failed':
            failed.append(rid)
collected = [records[rid] for rid in accepted_ids if rid in records]
factors = [r for r in collected if r['run']['research_kind'] == 'factor_evaluation']
strategies = [r for r in collected if 'summary' in r]
for r in collected:
    inp = r['run']['input']
    assert inp['universe'] == plan['universe'] and inp['neutralization'] == plan['neutralization']
    assert inp['end_date'] == plan['end_date']
    assert inp['formula'] in {f['formula'] for f in plan['factors']}
    assert r['provenance']['authoring_input'] == inp

lines = ['# 赢家条件内的收益符号连续性', '', '更新：' + now, '',
    '固定2025-09-10至2026-09-09、TOP3000、行业去均值关闭。一个条件增量候选，两个对照；不把形成期匹配或赢家筛选算作新独立家族。', '',
    'M为t−120到t−20累计收益，S为同一形成期100个日收益符号的均值。在M/S共同有效样本中保留M排名严格高于0.8且M为正的股票；候选按S排，同池对照按M排。另保留不加赢家筛选的S对照。[预声明](round23-plan.json)、[原始文献与改写边界](ROUND22_SOURCES.md)、[原生公式诊断](round23-formula-diagnostics.json)。', '',
    '|因子|角色|1日Rank IC|5日Rank IC|20日Rank IC|20日q5均值|20日配对差|20日有效/信号日|候选触发策略|',
    '|---|---|---:|---:|---:|---:|---:|---:|---|']
screen = []
for spec in plan['factors']:
    matches = [r for r in factors if r['run']['input']['formula'] == spec['formula']]
    assert len(matches) <= 1
    if not matches:
        lines.append(f"|{spec['item_key']}|{spec['role']}|—|—|—|—|—|—|待采集|")
        continue
    r = matches[0]
    assert r['run']['input']['start_date'] == plan['start_date']
    horizons = r['factor']['factor']['horizons']; h = horizons['20']; s = h['summary']; c = h['coverage']
    conditions = {'rank_ic_positive': positive(s['rank_ic']['mean']), 'q5_positive': positive(s['quantile_returns']['q5']),
        'paired_spread_positive': positive(s['top_bottom_return']),
        'coverage_at_least90percent': c['signal_session_count'] > 0 and c['rank_ic_valid_session_count'] / c['signal_session_count'] >= .9}
    selected = spec['role'] == 'candidate_conditional_increment' and all(conditions.values())
    screen.append({'key': spec['item_key'], 'run_id': r['run']['id'], 'conditions': conditions, 'selected_candidate': selected})
    metrics = '|'.join(num(horizons[str(day)]['summary']['rank_ic']['mean']) for day in (1, 5, 20))
    verdict = '是' if selected else ('否' if spec['role'] == 'candidate_conditional_increment' else '对照不单独触发')
    lines.append(f"|[{spec['item_key']}](https://thesistrace.com/research-runs/{r['run']['id']})|{spec['role']}|{metrics}|{pc(s['quantile_returns']['q5'])}|{pc(s['top_bottom_return'])}|{c['rank_ic_valid_session_count']}/{c['signal_session_count']}|{verdict}|")
selected = any(row['selected_candidate'] for row in screen)
required, comparisons = [], []
keys = plan['selection']['actual_if_factor_passes']['factor_keys']
for config in plan['selection']['actual_if_factor_passes']['strategies'] if selected else []:
    pair = []
    for key in keys:
        f = next(f for f in plan['factors'] if f['item_key'] == key)
        matches = [r for r in strategies if r['run']['input']['formula'] == f['formula'] and r['run']['input']['start_date'] == plan['start_date']
                   and r['run']['input']['holdings_count'] == config['holdings_count'] and r['run']['input']['rebalance_every_sessions'] == config['rebalance_every_sessions']]
        assert len(matches) <= 1
        if not matches:
            required.append({'key': key, **config})
        pair.append(matches[0] if matches else None)
    if all(pair):
        a, b = pair; am, bm = a['summary']['metrics'], b['summary']['metrics']
        conditions = {'sharpe_above1_2': am['sharpe'] is not None and am['sharpe'] > 1.2,
            'drawdown_at_most20percent': am['maximum_drawdown']['value'] <= .2,
            'sharpe_above_samepool_momentum': am['sharpe'] is not None and bm['sharpe'] is not None and am['sharpe'] > bm['sharpe'],
            'net_return_above_samepool_momentum': am['net_cumulative_return'] is not None and bm['net_cumulative_return'] is not None and am['net_cumulative_return'] > bm['net_cumulative_return']}
        comparisons.append({'candidate_run': a['run']['id'], 'control_run': b['run']['id'], **config,
            'conditions': conditions, 'followup_required': all(conditions.values())})
lines += ['', '筛选固定看20日：Rank IC、q5、逐日配对差都须为正，Rank IC有效日占全部信号日至少90%。1/5日也完整记录，不根据结果更换期限、方向或分位门槛。', '',
    '|实际账户|起点|净累计收益|最大回撤|Sharpe|', '|---|---|---:|---:|---:|']
for r in sorted(strategies, key=lambda r: r['run']['name']):
    m = r['summary']['metrics']
    assert float(r['summary']['initial_cash_cny']) == plan['constraints']['native_cash_cny']
    lines.append(f"|[{r['run']['name']}](https://thesistrace.com/research-runs/{r['run']['id']})|{r['run']['input']['start_date']}|{pc(m['net_cumulative_return'])}|{pc(m['maximum_drawdown']['value'])}|{num(m['sharpe'])}|")
if not strategies:
    lines.append('|尚无已采集实际账户结果|—|—|—|—|')
followup = [c for c in comparisons if c['followup_required']]
complete = len(factors) == len(plan['factors']) and not any((pending, pending_single, uncollected, failed, required, followup))
state = {'updated_at': now, 'source': 'SavedMCP evidence, renderer does not poll',
    'status': 'complete_fixed_round_no_further_followup' if complete else 'research_in_progress',
    'collected_factor_count': len(factors), 'factor_screen': screen, 'candidate_selected': selected,
    'collected_strategy_count': len(strategies), 'required_year_strategies_uncollected': required,
    'year_matched_comparisons': comparisons, 'year_pairs_requiring_followup': followup,
    'pending_batches': sorted(set(pending)), 'pending_single_runs': sorted(set(pending_single)),
    'succeeded_uncollected': sorted(set(uncollected)), 'failed_execution_attempts': sorted(set(failed))}
if complete:
    lines += ['', '本轮固定定义已结束：' + ('候选未通过因子筛选，没有触发实际账户、三年、季度或10万元回放。' if not selected else '实际账户没有通过全部预声明条件，没有触发三年、季度或10万元回放。')]
lines += ['', '若候选通过因子筛选，固定10/20只、每20日调仓，并同时执行同池动量对照。候选全年Sharpe>1.2、回撤≤20%，且Sharpe和净收益均高于同池对照，才触发两者相同参数的三年及季度验证。', '',
    '独立公式核对使用已在本地的2026-08-27行情：121个价格观测，对齐100个日收益，2869只共同有效股票、574只赢家。三个公式排名差异为0；候选与同池对照资格相同。该日最高10/20名分别重合4/4只，只说明排序不同，不证明经济独立性。[独立计数与排名证据](round23-signal-proof.json)。', '',
    '原论文约11个自然月形成、6个月持有、多空组合；这里使用既有100交易日形成期、20日标签及只做多执行，因此是本地改写。原生本金1000万元，不能线性缩放成10万元。最新10万元及板块权限仍未验证。', '',
    f"在跑批次：{', '.join(state['pending_batches']) or '无'}。成功待采集：{', '.join(state['succeeded_uncollected']) or '无'}。", '']
(ROOT / 'ROUND23_RESULTS.md').write_text('\n'.join(lines) + '\n')
(ROOT / 'round23-execution-state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(state, ensure_ascii=False))
