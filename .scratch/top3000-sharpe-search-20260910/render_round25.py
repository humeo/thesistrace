"""Summarize fixed daily-skewness experiment from saved MCP evidence."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ACTIVE = {'queued', 'running', 'cancelling'}
plan = json.loads((ROOT/'round25-plan.json').read_text())
records = {p.stem:json.loads(p.read_text()) for p in (ROOT/'results').glob('*.json')}
batches = {p.stem:json.loads(p.read_text()) for p in (ROOT/'batches').glob('*.json')}
runs = {p.stem:json.loads(p.read_text()) for p in (ROOT/'runs').glob('*.json')}
submissions = [json.loads(p.read_text()) for p in (ROOT/'submissions').glob('r25-*.json')]
now = datetime.now(timezone.utc).isoformat()
ids, pending, singles, uncollected, failed = set(), [], [], [], []
for sub in submissions:
    response=sub['response']
    if response.get('outcome')!='accepted':continue
    if 'batch_id' in response:
        bid=response['batch_id']; b=batches.get(bid)
        if not b or b['status'] in ACTIVE:pending.append(bid)
        items=b.get('items',[]) if b else []
    else:
        rid=response['run_id'];r=runs.get(rid)
        if not r or r['status'] in ACTIVE:singles.append(rid)
        items=[{'research_run_id':rid,'status':r['status'] if r else None}]
    for item in items:
        rid=item['research_run_id'];ids.add(rid)
        if item['status']=='succeeded' and rid not in records:uncollected.append(rid)
        if item['status']=='failed':failed.append(rid)
collected=[records[rid] for rid in ids if rid in records]
factors=[r for r in collected if r['run']['research_kind']=='factor_evaluation']
strategies=[r for r in collected if 'summary' in r]

def positive(v):return v is not None and math.isfinite(v) and v>0
def pc(v):return '空' if v is None else f'{v:.2%}'
def num(v):return '空' if v is None else f'{v:.4f}'
def year_pass(r):
    m=r['summary']['metrics']
    return m['sharpe'] is not None and m['sharpe']>1.2 and m['maximum_drawdown']['value']<=.2

lines=['# 日收益总偏度与MAX、低波动的对照','', '更新：'+now,'',
    '固定2025-09-10至2026-09-09、TOP3000、行业去均值关闭。一个反彩票家族内未测的三阶矩定义，两个匹配对照，不是三个独立经济家族。[预声明](round25-plan.json)、[一手资料和读取边界](ROUND24_SOURCES.md)。','',
    '候选为完整20个日收益的Fisher–Pearson总偏度负向排名，分母用总体标准差立方。MAX和低波动增加相同的零方差排除。没有市值、市场残差、期权或日内输入，不添加52周高点门槛。','',
    '|方向|角色|1日Rank IC|5日Rank IC|20日Rank IC|20日q5|20日配对差|20日有效/信号日|通过因子筛选|',
    '|---|---|---:|---:|---:|---:|---:|---:|---|']
screen=[]
for spec in plan['factors']:
    matches=[r for r in factors if r['run']['input']['formula']==spec['formula']]
    assert len(matches)<=1
    if not matches:
        lines.append(f"|{spec['item_key']}|{spec['role']}|—|—|—|—|—|—|待采集|")
        continue
    r=matches[0];horizons=r['factor']['factor']['horizons'];h=horizons['20'];s=h['summary'];c=h['coverage']
    conditions={'rank_ic_positive':positive(s['rank_ic']['mean']),'q5_positive':positive(s['quantile_returns']['q5']),
        'paired_spread_positive':positive(s['top_bottom_return']),'coverage90':c['signal_session_count']>0 and c['rank_ic_valid_session_count']/c['signal_session_count']>=.9}
    selected=spec['role']=='candidate' and all(conditions.values())
    screen.append({'key':spec['item_key'],'run_id':r['run']['id'],'role':spec['role'],'conditions':conditions,'selected_candidate':selected})
    metrics='|'.join(num(horizons[str(d)]['summary']['rank_ic']['mean']) for d in (1,5,20))
    verdict='是' if selected else ('否' if spec['role']=='candidate' else '对照不单独触发')
    lines.append(f"|[{spec['item_key']}](https://thesistrace.com/research-runs/{r['run']['id']})|{spec['role']}|{metrics}|{pc(s['quantile_returns']['q5'])}|{pc(s['top_bottom_return'])}|{c['rank_ic_valid_session_count']}/{c['signal_session_count']}|{verdict}|")
selected=any(s['selected_candidate'] for s in screen)
missing=[];year_rows=[];followup=[]
for r in collected:
    inp=r['run']['input']
    assert r['provenance']['authoring_input']==inp
    assert inp['universe']==plan['universe'] and inp['neutralization']==plan['neutralization'] and inp['end_date']==plan['end_date']
    assert inp['formula'] in {s['formula'] for s in plan['factors']}
for spec in plan['factors'] if selected else []:
    for config in plan['selection']['actual_if_candidate_passes']['strategies']:
        matches=[r for r in strategies if r['run']['input']['formula']==spec['formula'] and r['run']['input']['start_date']==plan['start_date']
            and all(r['run']['input'][k]==v for k,v in config.items())]
        assert len(matches)<=1
        if not matches:
            missing.append({'key':spec['item_key'],**config});continue
        r=matches[0];m=r['summary']['metrics']
        assert float(r['summary']['initial_cash_cny'])==10000000
        row={'key':spec['item_key'],'role':spec['role'],'run_id':r['run']['id'],**config,'net_return':m['net_cumulative_return'],
             'maximum_drawdown':m['maximum_drawdown']['value'],'sharpe':m['sharpe'],'passed_year':year_pass(r)}
        year_rows.append(row)
        if row['passed_year'] and spec['role']=='candidate':followup.append(row)
complete=len(factors)==3 and not any((pending,singles,uncollected,failed,missing,followup))
state={'updated_at':now,'source':'SavedMCP responses; this renderer does not poll','status':'complete_fixed_round_no_further_followup' if complete else 'research_in_progress',
    'collected_factor_count':len(factors),'factor_screen':screen,'candidate_selected':selected,'collected_strategy_count':len(strategies),
    'required_year_strategies_uncollected':missing,'year_strategy_results':year_rows,'candidate_year_pass_requires_followup':followup,
    'pending_batches':sorted(set(pending)),'pending_single_runs':sorted(set(singles)),'succeeded_uncollected':sorted(set(uncollected)),'failed_run_attempts':sorted(set(failed))}
lines+=['','仅20日Rank IC、q5与逐日配对差为正，且Rank IC有效/全部信号日至少90%才继续。所有期限、分组及负结果均保留；q4高于q5作为警示，不改阈值。','',
    '|实际策略|持仓/调仓|累计净收益|最大回撤|Sharpe|全年通过|','|---|---|---:|---:|---:|---|']
for r in year_rows:
    lines.append(f"|[{r['key']}](https://thesistrace.com/research-runs/{r['run_id']})|{r['holdings_count']}/{r['rebalance_every_sessions']}|{pc(r['net_return'])}|{pc(r['maximum_drawdown'])}|{num(r['sharpe'])}|{'是' if r['passed_year'] else '否'}|")
if not year_rows:lines.append('|尚无已采集实际策略|—|—|—|—|—|')
if complete:lines+=['','固定定义已结束：'+('候选未通过因子筛选，没有触发实际策略。' if not selected else '候选实际账户未达到预设条件，没有触发后续验证。')]
if complete and not selected:
    lines+=['','本轮20日总偏度Rank IC虽为+0.0147，最高组均值−0.049%、配对差−0.069%，两项收益条件均失败。1/5日正向结果保留，不能事后换期限触发策略。两个对照与已测原始MAX/低波动的摘要比较另存[对照可比性](round25-control-comparability.json)，摘要相同不等于证明每个评分或持仓都相同。']
lines+=['','候选因子通过时同时执行候选/MAX/低波动的10/20只、每20日调仓策略；候选全年Sharpe>1.2且回撤≤20%才触发相同参数的三年、季度和可用10万元回放。对照单独过线不触发新的择优搜索。','',
    '五个预先指定本地日期共44,616个评分，直接第三中心矩与DSL原始矩展开的排名完全一致，最大数值差2.67e−15；三者资格一致。[独立核对](round25-signal-proof.json)。这不证明远端所有评分或经济收益。','',
    '论文上月日收益、多空月收益和有限样本规则未完整取得；这里明确采用固定20交易日、完整窗口、次日开盘执行，只检验自定义的现货多头规则。低偏度不等于低回撤。原生本金1000万元，不能直接缩放为10万元。','',
    f"在跑批次：{', '.join(state['pending_batches']) or '无'}。成功待采集：{', '.join(state['succeeded_uncollected']) or '无'}。",'']
(ROOT/'round25-execution-state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
(ROOT/'ROUND25_RESULTS.md').write_text('\n'.join(lines)+'\n')
print(json.dumps(state,ensure_ascii=False))
