"""Render declared coverage gaps from saved MCP submissions and Results."""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ACTIVE = {'queued', 'running', 'cancelling'}
plan = json.loads((ROOT / 'round22-plan.json').read_text())
records = {p.stem: json.loads(p.read_text()) for p in (ROOT / 'results').glob('*.json')}
batches = {p.stem: json.loads(p.read_text()) for p in (ROOT / 'batches').glob('*.json')}
runs = {p.stem: json.loads(p.read_text()) for p in (ROOT / 'runs').glob('*.json')}
submissions = {p.stem: json.loads(p.read_text()) for p in (ROOT / 'submissions').glob('r22-*.json')}
now = datetime.now(timezone.utc).isoformat()

def pc(v):
    return '空' if v is None else f'{v:.2%}'

def num(v):
    return '空' if v is None else f'{v:.3f}'

pending_batches, pending_single, uncollected, failed = [], [], [], []
for key, s in submissions.items():
    response = s['response']
    if response.get('outcome') != 'accepted':
        continue
    if 'batch_id' in response:
        bid = response['batch_id']; b = batches.get(bid)
        if b is None or b['status'] in ACTIVE:
            pending_batches.append(bid)
        items = b.get('items', []) if b else []
    else:
        rid = response['run_id']; r = runs.get(rid)
        if r is None or r['status'] in ACTIVE:
            pending_single.append(rid)
        items = [{'research_run_id': rid, 'status': r.get('status') if r else None}]
    for item in items:
        rid = item['research_run_id']
        if item['status'] == 'succeeded' and rid not in records:
            uncollected.append(rid)
        if item['status'] == 'failed':
            failed.append(rid)

lines = ['# 既有正向因子的实际策略覆盖补齐', '', '更新：' + now, '',
    '九项均来自已看过的最新年因子结果。本轮不新增公式，不把中性化、组合或持仓参数变体算作独立Alpha。此前QS19覆盖七项，现按同一正向条件补齐其余未接受过实际策略任务的案例。效率变化的资源失败另行保留，没有原样重提。', '',
    '固定区间2025-09-10至2026-09-09、TOP3000、10或20只、每20交易日调仓；保留各原因子的行业去均值选择。原生本金1000万元、默认费用，无杠杆，不能直接缩放成10万元账户。[提交前预声明](round22-plan.json)、[全量筛选审计](round22-selection-audit.json)、[数据状态](round22-research-context.json)。', '',
    '|因子案例|20日Rank IC|20日q5均值|20日配对差均值|q4高于q5|',
    '|---|---:|---:|---:|---|']
for c in plan['candidates']:
    e = c['evidence']
    lines.append(f"|[{c['key']}](https://thesistrace.com/research-runs/{c['source_factor_run']})|{num(e['rank_ic20'])}|{pc(e['q5_20'])}|{pc(e['paired_spread20'])}|{'是' if e['q4_20'] > e['q5_20'] else '否'}|")
lines += ['', '筛选条件为20日Rank IC、q5和逐日配对差均值均正，Rank IC日覆盖至少90%，且同公式/区间/股票池/中性化尚无已接受的实际策略尝试。极小分组收益及q4高于q5的警示保留，不事后改阈值。因子标签均值尚未扣相同的持仓与费用，不能用它代替连续账户结果。', '',
    '|实际策略|累计净收益|最大回撤|Sharpe|状态／全年通过|', '|---|---:|---:|---:|---|']
rows, missing = [], []
for c in plan['candidates']:
    key = 'r22-strategy-' + c['key']; s = submissions.get(key)
    items = batches.get(s['response'].get('batch_id'), {}).get('items', []) if s else []
    for spec in plan['strategies']:
        item_key = f"h{spec['holdings_count']}r{spec['rebalance_every_sessions']}"
        item = next((i for i in items if i['item_key'] == item_key), None)
        rid = item['research_run_id'] if item else None
        name = f"{c['key']} H{spec['holdings_count']} R{spec['rebalance_every_sessions']}"
        r = records.get(rid)
        if r is None:
            status = item['status'] if item else (s['response'].get('outcome', '未观察') if s else '未提交')
            lines.append(f"|{name}|—|—|—|{status}，无已采集Result|")
            missing.append({'candidate': c['key'], 'holdings_count': spec['holdings_count'], 'run_id': rid, 'status': status})
            continue
        inp = r['run']['input']; m = r['summary']['metrics']
        assert inp['formula'] == c['formula'] and inp['neutralization'] == c['neutralization']
        assert inp['start_date'] == plan['start_date'] and inp['end_date'] == plan['end_date'] and inp['universe'] == plan['universe']
        assert inp['holdings_count'] == spec['holdings_count'] and inp['rebalance_every_sessions'] == spec['rebalance_every_sessions']
        passed = m['sharpe'] is not None and m['sharpe'] > 1.2 and m['maximum_drawdown']['value'] <= .2
        rows.append({'candidate': c['key'], 'run_id': rid, 'holdings_count': inp['holdings_count'], 'rebalance_every_sessions': inp['rebalance_every_sessions'], 'net_return': m['net_cumulative_return'], 'maximum_drawdown': m['maximum_drawdown']['value'], 'sharpe': m['sharpe'], 'passed_year': passed, 'source_factor_run': c['source_factor_run']})
        lines.append(f"|[{name}](https://thesistrace.com/research-runs/{rid})|{pc(m['net_cumulative_return'])}|{pc(m['maximum_drawdown']['value'])}|{num(m['sharpe'])}|{'是' if passed else '否'}|")
passing = [r['run_id'] for r in rows if r['passed_year']]
state = {'updated_at': now, 'source': 'Saved MCP responses; renderer does not poll live state',
    'declared_factor_cases': len(plan['candidates']), 'required_year_strategies': 2 * len(plan['candidates']),
    'collected_year_strategies': len(rows), 'strategy_results': rows, 'uncollected_year_cases': missing,
    'pending_batches': sorted(set(pending_batches)), 'pending_single_runs': sorted(set(pending_single)),
    'succeeded_uncollected': sorted(set(uncollected)), 'failed_execution_attempts': sorted(set(failed)),
    'year_pass_requires_followup': passing}
state['status'] = 'year_complete_no_followup' if not missing and not passing and not pending_batches and not pending_single else ('year_pass_requires_followup' if not missing and passing else 'research_in_progress')
lines += ['', f"已采集{len(rows)}/{state['required_year_strategies']}项全年策略，{len(passing)}项通过。未完成、失败和已完成的经济负结果分开记录。", '',
    '仅实际全年Sharpe>1.2且回撤≤20%触发相同参数的固定三年（2023-09-11起）和季度（2026-06-11起）验证。已经看过的历史仍属探索，不能称未接触的样本外。不在本轮结果出来后继续调频率、符号或门槛。', '',
    f"在跑批次：{', '.join(state['pending_batches']) or '无'}。在跑单任务：{', '.join(state['pending_single_runs']) or '无'}。成功待采集：{', '.join(state['succeeded_uncollected']) or '无'}。", '',
    '行业去均值作用于Alpha，不等于实际组合行业中性。10万元本金、板块权限和最新行情回放仍需独立证据；原始行情导出授权未解决，不据此停止可用MCP上的研究，也不绕过传输审批。', '']
nav_path = ROOT / 'round22-high-return-nav-audit.json'
if nav_path.exists():
    audit = json.loads(nav_path.read_text())
    state['highest_return_nav_audit'] = 'round22-high-return-nav-audit.json'
    lines += [f"本轮收益最高WQ002 H10的{audit['observations']}条完整净值已另用Decimal复算：累计净收益{pc(audit['independent_net_return'])}、最大回撤{pc(audit['independent_maximum_drawdown'])}、Sharpe{num(audit['independent_sharpe'])}，与平台摘要一致。峰值{audit['peak_session']}、谷值{audit['trough_session']}；高收益仍不符合20%回撤目标。[完整净值审计](round22-high-return-nav-audit.json)。", '']
(ROOT / 'round22-execution-state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
(ROOT / 'ROUND22_RESULTS.md').write_text('\n'.join(lines) + '\n')
print(json.dumps({k: state[k] for k in ['status', 'collected_year_strategies', 'pending_batches', 'failed_execution_attempts', 'year_pass_requires_followup']}))
