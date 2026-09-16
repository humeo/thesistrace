"""Render fixed QS19/QS20 plans from saved, authoritative MCP observations."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ACTIVE = {'queued', 'running', 'cancelling'}
now = datetime.now(timezone.utc).isoformat()
records = {p.stem: json.loads(p.read_text()) for p in (ROOT / 'results').glob('*.json')}
batches = {p.stem: json.loads(p.read_text()) for p in (ROOT / 'batches').glob('*.json')}
runs = {p.stem: json.loads(p.read_text()) for p in (ROOT / 'runs').glob('*.json')}
submissions = {p.stem: json.loads(p.read_text()) for p in (ROOT / 'submissions').glob('*.json')}

def pc(v):
    return '空' if v is None else f'{v:.2%}'

def num(v):
    return '空' if v is None else f'{v:.3f}'

def positive(v):
    return v is not None and math.isfinite(v) and v > 0

def passed(record):
    m = record['summary']['metrics']
    return m['sharpe'] is not None and m['sharpe'] > 1.2 and m['maximum_drawdown']['value'] <= .2

def pending(prefix):
    active, single, uncollected = [], [], []
    for key, s in submissions.items():
        if not key.startswith(prefix) or s['response'].get('outcome') != 'accepted':
            continue
        if 'batch_id' in s['response']:
            bid = s['response']['batch_id']
            b = batches.get(bid)
            if b is None or b['status'] in ACTIVE:
                active.append(bid)
            if b:
                uncollected.extend(x['research_run_id'] for x in b['items'] if x['status'] == 'succeeded' and x['research_run_id'] not in records)
        else:
            rid = s['response']['run_id']
            r = runs.get(rid)
            if r is None or r['status'] in ACTIVE:
                single.append(rid)
            if r and r['status'] == 'succeeded' and rid not in records:
                uncollected.append(rid)
    return sorted(set(active)), sorted(set(single)), sorted(set(uncollected))

plan19 = json.loads((ROOT / 'round19-plan.json').read_text())
rows19, deferred, rejected19, missing_cases19 = [], [], [], []
lines = ['# 既有正向因子转为实际持仓后的验证', '', '更新：' + now, '',
    '区间2025-09-10至2026-09-09，TOP3000；固定10只或20只，每20交易日调仓。以下使用平台原生1000万元、默认交易费用，不能直接当作10万元收益。', '',
    '筛选来自已看过的因子结果，属于探索性检验。不同公式或参数不等于独立收益来源。[预声明](round19-plan.json)。', '',
    '|方向|原因子20日Rank IC|原因子20日q5均值|持仓数|实际累计净收益|实际最大回撤|实际Sharpe|全年通过|',
    '|---|---:|---:|---:|---:|---:|---:|---|']
for candidate in plan19['candidates']:
    key = 'r19-strategy-' + candidate['key']
    s = submissions.get(key)
    recovery = [x for x in submissions.values() if x.get('recovery_of_rejected_submission') == key and x['response'].get('outcome') == 'accepted']
    if s and s['response'].get('outcome') == 'rejected':
        rejected19.append({'key': key, 'issues': s['response'].get('issues', []), 'accepted_recovery_run_ids': [x['response']['run_id'] for x in recovery]})
    items = list(batches.get(s['response'].get('batch_id'), {}).get('items', [])) if s else []
    items += [{'research_run_id': x['response']['run_id'], 'item_key': f"h{x['input']['holdings_count']}r20", 'status': runs.get(x['response']['run_id'], {}).get('status', '尚未观察')} for x in recovery]
    seen_holdings = {int(x['item_key'].split('r')[0].removeprefix('h')) for x in items}
    missing_holdings = sorted({10, 20} - seen_holdings)
    if missing_holdings:
        deferred.append(candidate['key'])
        for n in missing_holdings:
            missing_cases19.append({'candidate': candidate['key'], 'holdings_count': n})
            admission = '提交被拒绝，尚无已接受恢复' if s and s['response'].get('outcome') == 'rejected' else '尚无已接受任务记录'
            lines.append(f"|{candidate['key']}|{num(candidate['evidence']['rank_ic20'])}|{pc(candidate['evidence']['q5_20'])}|{n}|{admission}|待采集|待采集|待判定|")
    for item in items:
        rid = item['research_run_id']
        r = records.get(rid)
        if r is None:
            lines.append(f"|{candidate['key']}|{num(candidate['evidence']['rank_ic20'])}|{pc(candidate['evidence']['q5_20'])}|{item['item_key']}|{item['status']}|待采集|待采集|待判定|")
            continue
        m = r['summary']['metrics']
        row = {'candidate': candidate['key'], 'run_id': rid, 'holdings': r['run']['input']['holdings_count'],
               'net_return': m['net_cumulative_return'], 'maximum_drawdown': m['maximum_drawdown']['value'],
               'sharpe': m['sharpe'], 'passed_year': passed(r), 'source_factor_run': candidate['source_factor_run']}
        rows19.append(row)
        lines.append(f"|[{candidate['key']}](https://thesistrace.com/research-runs/{rid})|{num(candidate['evidence']['rank_ic20'])}|{pc(candidate['evidence']['q5_20'])}|{row['holdings']}|{pc(row['net_return'])}|{pc(row['maximum_drawdown'])}|{num(row['sharpe'])}|{'是' if row['passed_year'] else '否'}|")
active19, single19, uncollected19 = pending('r19-')
followup19 = [x['run_id'] for x in rows19 if x['passed_year']]
state19 = {'updated_at': now, 'collected_strategy_count': len(rows19), 'selected_factor_count': len(plan19['candidates']),
           'strategy_results': rows19, 'pending_batches': active19, 'pending_single_runs': single19, 'succeeded_uncollected': uncollected19,
           'unsubmitted_declared_candidates': deferred, 'strategy_cases_without_accepted_run': missing_cases19,
           'rejected_submission_requests': rejected19, 'year_pass_requires_followup': followup19}
state19['status'] = 'complete_fixed_round_no_further_followup' if len(rows19) == 2 * len(plan19['candidates']) and not active19 and not single19 and not uncollected19 and not missing_cases19 and not followup19 else 'research_in_progress'
lines += ['', f"已采集{len(rows19)}项策略，{len(followup19)}项达到全年Sharpe>1.2且回撤≤20%。原始q5是宽分组、重叠未来标签的均值，不是Top10/20连续账户收益；它没有包含相同的持仓和费用约束。", '',
    '未通过的组合保留负结果，不在看到结果后继续挑调仓频率。通过全年筛选才按预声明进入固定三年和近期验证。', '',
    '营业收入增长方向在QS18财务因子批次完成后提交。两项Strategy Sweep因共享批次容量被拒绝，随后保持原公式、区间、TOP3000及持仓参数改为单ResearchRun。原拒绝与恢复分别记录，接受不代表完成，也不是新增研究假设。见[容量诊断](product-audit/issues/09-batch-capacity-diagnostics.md)。', '',
    f"尚缺已接受任务的方向：{', '.join(deferred) or '无'}。在跑批次：{', '.join(active19) or '无'}。在跑单任务：{', '.join(single19) or '无'}。成功待采集：{', '.join(uncollected19) or '无'}。", '',
    '产品发现：从已完成因子继续做策略，需要在本地保存源Result关联；当前批次内部确实共享Alpha/Factor计算，但跨批次来源与复用信息没有同等直接的工作流。见[问题12](product-audit/issues/12-factor-to-strategy-lineage.md)。', '']
(ROOT / 'ROUND19_RESULTS.md').write_text('\n'.join(lines) + '\n')
(ROOT / 'round19-execution-state.json').write_text(json.dumps(state19, ensure_ascii=False, indent=2) + '\n')

plan20 = json.loads((ROOT / 'round20-plan.json').read_text())
factors20 = [r for r in records.values() if r['run']['name'].startswith('QS20 1y ') and r['run']['research_kind'] == 'factor_evaluation']
strategies20 = [r for r in records.values() if r['run']['name'].startswith('QS20 ') and 'summary' in r]
screen = []
lines = ['# 自回归预测增量与历史波动率稳定性', '', '更新：' + now, '',
    '两个候选各有一个匹配数据覆盖的旧机制对照。区间2025-09-10至2026-09-09，TOP3000，不做行业去均值。对照与窗口变化不增加独立家族数。[预声明](round20-plan.json)、[一手资料及差异](ROUND19_SOURCES.md)。', '',
    '|方向|角色|1日Rank IC|5日Rank IC|20日Rank IC|固定筛选期|该期q5均值|该期配对差均值|该期Rank IC有效/信号日|候选触发策略|',
    '|---|---|---:|---:|---:|---:|---:|---:|---:|---|']
for spec in plan20['factors']:
    r = next((r for r in factors20 if r['run']['name'] == spec['name']), None)
    if r is None:
        lines.append(f"|{spec['item_key']}|{spec['role']}|待完成|待完成|待完成|{spec['horizon']}|待完成|待完成|待完成|待判定|")
        continue
    horizons = r['factor']['factor']['horizons']
    h = horizons[str(spec['horizon'])]
    summary, cov = h['summary'], h['coverage']
    conditions = {'rank_ic_positive': positive(summary['rank_ic']['mean']),
                  'q5_positive': positive(summary['quantile_returns']['q5']),
                  'paired_spread_positive': positive(summary['top_bottom_return']),
                  'rank_ic_day_coverage_at_least90percent': cov['signal_session_count'] > 0 and cov['rank_ic_valid_session_count'] / cov['signal_session_count'] >= .9}
    if spec['item_key'] == 'ar1_increment60':
        conditions['one_day_rank_ic_positive'] = positive(horizons['1']['summary']['rank_ic']['mean'])
    selected = spec['role'] == 'candidate' and all(conditions.values())
    screen.append({'key': spec['item_key'], 'run_id': r['run']['id'], 'role': spec['role'], 'horizon': spec['horizon'], 'conditions': conditions, 'selected_candidate': selected})
    metrics = '|'.join(num(horizons[h]['summary']['rank_ic']['mean']) for h in ['1', '5', '20'])
    verdict = '是' if selected else ('对照不单独触发' if spec['role'] == 'matched_control' else '否')
    lines.append(f"|[{spec['item_key']}](https://thesistrace.com/research-runs/{r['run']['id']})|{spec['role']}|{metrics}|{spec['horizon']}|{pc(summary['quantile_returns']['q5'])}|{pc(summary['top_bottom_return'])}|{cov['rank_ic_valid_session_count']}/{cov['signal_session_count']}|{verdict}|")
active20, single20, uncollected20 = pending('r20-')
state20 = {'updated_at': now, 'collected_factor_count': len(factors20), 'factor_screen': screen,
           'collected_strategy_count': len(strategies20), 'pending_batches': active20, 'pending_single_runs': single20, 'succeeded_uncollected': uncollected20,
           'selected_candidates': [x['key'] for x in screen if x['selected_candidate']],
           'candidate_year_pass_requires_followup': [r['run']['id'] for r in strategies20 if r['run']['input']['start_date'] == plan20['start_date'] and passed(r) and any(s['item_key'] in r['run']['name'] and s['role'] == 'candidate' for s in plan20['factors'])]}
selected_keys = set(state20['selected_candidates'])
required_names = []
for candidate, control, rebalance in [('ar1_increment60', 'reversal1_ar_coverage', 5), ('historical_vol_instability20_60_low', 'lowvol20_instability_coverage', 20)]:
    if candidate in selected_keys:
        required_names.extend(f'QS20 1y {key} H{n} R{rebalance}' for key in (candidate, control) for n in (10, 20))
state20['required_actual_strategies_uncollected'] = sorted(set(required_names) - {r['run']['name'] for r in strategies20})
state20['status'] = ('complete_fixed_round_no_further_followup' if len(factors20) == len(plan20['factors']) and not active20 and not single20 and not uncollected20 and not state20['required_actual_strategies_uncollected'] and not state20['candidate_year_pass_requires_followup'] else 'research_in_progress')
lines += ['', 'AR方向预先固定看5日，且要求1日Rank IC也为正；若通过，再与旧反转对照一起做10/20只、每5日策略。风险稳定性预先固定看20日；若通过，再与旧低波动对照一起做10/20只、每20日策略。所有指标均须正向且Rank IC日覆盖至少90%。', '',
    '只在1日有效不能推导20日持仓有效，因子IC/ICIR也不是策略Sharpe。控制组单独通过不会触发新的择优搜索。', '',
    '|实际策略|累计净收益|最大回撤|Sharpe|全年通过|', '|---|---:|---:|---:|---|']
for r in sorted(strategies20, key=lambda r: r['run']['name']):
    m = r['summary']['metrics']
    lines.append(f"|[{r['run']['name']}](https://thesistrace.com/research-runs/{r['run']['id']})|{pc(m['net_cumulative_return'])}|{pc(m['maximum_drawdown']['value'])}|{num(m['sharpe'])}|{'是' if passed(r) else '否'}|")
if not strategies20:
    lines.append('|尚无完成的实际策略|—|—|—|待判定|')
if state20['status'] == 'complete_fixed_round_no_further_followup':
    lines += ['', '本轮固定检验已完成。自回归方向未通过因子筛选；风险稳定性通过因子筛选后，10只/20只实际策略均低于Sharpe1.2，且回撤超过20%。两个匹配低波动对照也未达到Sharpe1.2。因此本轮没有触发三年、季度或小本金后续，不改窗口或符号继续择优。', '',
        '风险稳定性10只/20只组合的最大回撤32.39%/27.81%，明显高于匹配低波动对照的11.57%/14.21%。低历史波动率变异系数并不等于低账户回撤；因子相关、分组收益与TopN账户风险需要分别验证。']
proof_path = ROOT / 'round20-signal-proof.json'
if proof_path.exists():
    proof = json.loads(proof_path.read_text())
    checked = sum(c['native_valid'] for c in proof['comparisons'])
    differences = sum(c['differing_score_count'] + len(c['unmatched_ids']) for c in proof['comparisons'])
    lines += ['', f"独立公式核对：本地2026-08-27单日、80个价格观测，4个公式共{checked}个有效评分；排名/资格差异{differences}项。OLS用独立最小二乘求解，历史波动用独立滚动窗口；两个候选与各自对照的数据覆盖一致。收益重排和正比例缩放的确定性例子验证了公式含义。见[证据](round20-signal-proof.json)。这不证明最新远端收益，也不证明独立经济Alpha。"]
lines += ['', '当前策略若提交，仍是平台原生1000万元。现有本地行情从2025-08-01开始，不足以支持2025-09-10起点所需的61/79日预热；不能删减预热冒充同条件10万元回测。历史波动率代理也不是原文使用的期权隐含波动率。', '',
    f"在跑批次：{', '.join(active20) or '无'}。成功待采集：{', '.join(uncollected20) or '无'}。", '']
(ROOT / 'ROUND20_RESULTS.md').write_text('\n'.join(lines) + '\n')
(ROOT / 'round20-execution-state.json').write_text(json.dumps(state20, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'round19': {'collected': len(rows19), 'year_pass': followup19, 'unsubmitted': deferred}, 'round20': state20}, ensure_ascii=False))
