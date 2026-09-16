"""Render QS18 from persisted MCP records, including unresolved jobs."""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent
plan=json.loads((ROOT/'round18-plan.json').read_text())
records=[json.loads(p.read_text()) for p in (ROOT/'results').glob('*.json')]
factors=[r for r in records if r['run']['name'].startswith('QS18 ') and r['run']['research_kind']=='factor_evaluation']
strategies=[r for r in records if r['run']['name'].startswith('QS18 ') and 'summary' in r]
submissions=[json.loads(p.read_text()) for p in (ROOT/'submissions').glob('r18-*.json')]
batches={r['id']:r for r in [json.loads(p.read_text()) for p in (ROOT/'batches').glob('*.json')]}
runs={r['id']:r for r in [json.loads(p.read_text()) for p in (ROOT/'runs').glob('*.json')]}
pending=[];pending_single=[];uncollected=[];result_ids={r['run']['id'] for r in records}
rejected=[{'key':s['key'],'issues':s['response'].get('issues',[])} for s in submissions if s.get('response',{}).get('outcome')=='rejected']
failed=[{'run_id':s['response']['run_id'],'submission_key':s['key'],'failure_reason':runs[s['response']['run_id']].get('failure_reason'),'progress':runs[s['response']['run_id']].get('progress')} for s in submissions if s.get('response',{}).get('run_id') in runs and runs[s['response']['run_id']]['status']=='failed']
for s in submissions:
    response=s.get('response',{})
    if response.get('outcome')!='accepted':continue
    if 'batch_id' in response:
        bid=response['batch_id'];batch=batches.get(bid)
        if not batch or batch['status'] in {'queued','running','cancelling'}:pending.append(bid)
        if batch:
            uncollected.extend(i['research_run_id'] for i in batch['items'] if i['status']=='succeeded' and i['research_run_id'] not in result_ids)
    else:
        rid=response['run_id'];run=runs.get(rid)
        if not run or run['status'] in {'queued','running','cancelling'}:pending_single.append(rid)
        if run and run['status']=='succeeded' and rid not in result_ids:uncollected.append(rid)
screen=[]
for r in factors:
    spec=next(f for f in plan['factors'] if f['formula']==r['run']['input']['formula'])
    h=r['factor']['factor']['horizons']['20'];s=h['summary'];q=s['quantile_returns'];c=h['coverage']
    condition={'rank_ic20_positive':s['rank_ic']['mean'] is not None and s['rank_ic']['mean']>0,
               'q5_positive':q['q5'] is not None and q['q5']>0,
               'separate_q5_q1_means_positive':q['q5'] is not None and q['q1'] is not None and q['q5']>q['q1'],
               'rank_ic_day_coverage_at_least90percent':c['rank_ic_valid_session_count']/c['signal_session_count']>=.9}
    same_strategies=[x for x in strategies if x['run']['input']['formula']==spec['formula']]
    screen.append({'key':spec['item_key'],'run_id':r['run']['id'],'conditions':condition,
                   'selected':all(condition.values()),'matching_strategy_results':[x['run']['id'] for x in same_strategies],
                   'paired_spread':s['top_bottom_return'],
                   'difference_of_means':None if q['q5'] is None or q['q1'] is None else q['q5']-q['q1']})
await_strategy=[r['key'] for r in screen if r['selected'] and len(r['matching_strategy_results'])<2]
passed=[r['run']['id'] for r in strategies if r['summary']['metrics']['sharpe']>1.2 and r['summary']['metrics']['maximum_drawdown']['value']<=.2]
all_collected=len(factors)==len(plan['factors']) and not pending and not pending_single and not uncollected and not await_strategy
plan['status']='all_declared_factors_and_selected_strategies_collected' if all_collected else ('selected_strategy_execution_resource_limited' if failed and await_strategy and not pending and not pending_single else 'research_in_progress')
plan['last_report_at']=datetime.now(timezone.utc).isoformat()
plan['factor_screen']=screen
plan['pending_batches']=sorted(set(pending))
plan['pending_single_runs']=sorted(set(pending_single))
plan['rejected_submission_requests']=rejected
plan['failed_execution_attempts']=failed
plan['succeeded_uncollected']=sorted(set(uncollected))
plan['selected_factor_strategies_outstanding']=await_strategy
plan['native_strategies_passing_year']=passed
(ROOT/'round18-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
(ROOT/'round18-factor-screen.json').write_text(json.dumps(screen,ensure_ascii=False,indent=2)+'\n')
lines=['# 经营效率、成交活动稳定性与日线价差代理','',
       '更新：'+plan['last_report_at'],'',
       f"已采集{len(factors)}/6项预先固定的因子方向/对照、{len(strategies)}项实际策略。三个研究方向并不等于三个已证明独立的收益来源；反号与匹配水平对照不增加家族数。数据固定到2026-09-09，区间从2025-09-10开始。",'',
       '成交额稳定性方向通过因子初筛，实际10只和20只/每20交易日组合均未通过Sharpe1.2；低价差方向虽有正20日Rank IC，q5平均收益却为负，也未达到预声明筛选条件。','',
       '策略仍用平台固定1000万元，无杠杆，默认费用；不等于用户10万元账户。[完整预声明](round18-plan.json)、[一手论文及与实现的差异](ROUND17_SOURCES.md)。','',
       '|因子方向|1日Rank IC|5日Rank IC|20日Rank IC|20日q5均值|20日每日多空差均值|20日Rank IC有效/信号日|是否进入实际策略|',
       '|---|---:|---:|---:|---:|---:|---:|---|']
for spec in plan['factors']:
    found=[r for r in factors if r['run']['input']['formula']==spec['formula']]
    if not found:
        lines.append(f"|{spec['item_key']}|待完成|待完成|待完成|待完成|待完成|待完成|待判定|");continue
    r=found[0];hs=r['factor']['factor']['horizons'];s=hs['20']['summary'];c=hs['20']['coverage']
    verdict=next(v for v in screen if v['key']==spec['item_key'])
    def num(v):return '空' if v is None else f'{v:.4f}'
    def pc(v):return '空' if v is None else f'{v:.4%}'
    ics=[num(hs[h]['summary']['rank_ic']['mean']) for h in ['1','5','20']]
    lines.append(f"|[{spec['item_key']}](https://thesistrace.com/research-runs/{r['run']['id']})|"+'|'.join(ics)+f"|{pc(s['quantile_returns']['q5'])}|{pc(s['top_bottom_return'])}|{c['rank_ic_valid_session_count']}/{c['signal_session_count']}|{'是' if verdict['selected'] else '否'}|")
lines+=['','q5是因子标签的等权分组均值，不是扣成本的连续账户收益；IC没有直接可比的策略Sharpe。截止日前没有完整未来标签的信号日不会参与对应预测期均值。','',
        '## 已完成的连续账户策略','',
        '|参数|累计净收益|最大回撤|Sharpe|费用/初始本金|通过全年筛选|',
        '|---|---:|---:|---:|---:|---|']
for r in sorted(strategies,key=lambda r:r['run']['name']):
    m=r['summary']['metrics'];name=r['run']['name'];rid=r['run']['id']
    lines.append(f"|[{name}](https://thesistrace.com/research-runs/{rid})|{m['net_cumulative_return']:.2%}|{m['maximum_drawdown']['value']:.2%}|{m['sharpe']:.3f}|{m['transaction_costs']['ratio']:.2%}|{'是' if rid in passed else '否'}|")
lines+=['','仅当同一全年策略同时Sharpe>1.2、回撤≤20%时，按计划安排三年/近期及小资金验证。低CV两项不触发后续；没有改用另一个预测期、分位或调仓频率来追加择优。','',
        '## 分组覆盖的诊断发现','',
        'CHL代理先对样本矩截零，会产生大量并列。低价差20日q5=-3.1855%，q1=+0.0821%，两个均值的差为-3.2676%，而逐日两端差的均值为-0.2774%。这几项可能来自不同有效日期；手工两日例子已与当前计算核对。','',
        '本地233个信号日，未筛未来标签前q5为空193日。该统计截至8月27日，不等于远端9月9日结果的精确有效日。MCP只返回整体quantile_valid_session_count，缺每组与配对差值的有效日期数。见[分组覆盖证据](QUANTILE_COVERAGE.md)。','',
        '## 尚未完成','']
if pending or pending_single or uncollected or await_strategy:
    for bid in sorted(set(pending)):
        lines.append(f"- 批次 `{bid}`：继续原ID；尚未把接受或运行中当作完成。")
        b=batches.get(bid,{})
        for item in b.get('items',[]):
            if item['status'] not in {'queued','running','cancelling'}:continue
            p=runs.get(item['research_run_id'],{}).get('progress',{})
            lines.append(f"  - `{item['research_run_id']}`：{item['item_key']}，{item['status']}；最近已观察研究进度{p.get('completed_research_sessions','未知')}/{p.get('total_research_sessions','未知')}。")
    for rid in sorted(set(pending_single)):
        r=runs.get(rid,{});p=r.get('progress',{})
        lines.append(f"- 单任务 `{rid}`：{r.get('status','尚未观察')}，阶段{p.get('phase','未知')}；最近已观察研究进度{p.get('completed_research_sessions','未知')}/{p.get('total_research_sessions','未知')}。继续原ID，不重复提交。")
    if uncollected:lines.append('- 已成功待采集：'+', '.join(uncollected))
    if await_strategy:lines.append('- 已过因子初筛且实际策略仍待完成：'+', '.join(await_strategy))
    for f in failed:
        lines.append(f"- 单任务 `{f['run_id']}` 已失败：{f['failure_reason']}。未产生Result，不能填入收益或计作经济负结果；不会原样重提已确定的资源失败。")
else:lines.append('预声明因子及筛选出的实际策略均已采集；后续验证是否需要执行，以通过全年筛选的策略清单为准。')
if rejected:
    lines+=['','效率变化的两项Strategy Sweep因共享批次容量被拒绝，未创建批次或策略。保持原公式、TOP3000、区间和10/20只、20日调仓参数，改为单ResearchRun提交；单任务是否完成以上述状态和Result为准。拒绝记录不计作经济负结果。见[容量诊断](product-audit/issues/09-batch-capacity-diagnostics.md)。']
lines+=['','当前252交易日财务滞后只表示相隔252个研究交易日的可见字段，不能声称精确年度财报同比或完整Piotroski F-score。价差代理不是实测盘口，也不能替代滑点。[2025年成交活动研究](https://onlinelibrary.wiley.com/doi/full/10.1111/jtsa.12802)还提示方向会随采样变化，因此本文不从文献继承收益保证。','']
if (ROOT/'round24-execution-state.json').exists():
    lines+=['[QS24等价恢复](ROUND24_RESULTS.md)：22节点原式简写为11节点delta后，单H10任务仍在第68个研究日因资源限制失败，没有Result；依照预声明停止H20派发。该恢复没有改变252回看或经济定义，两项实际策略仍未完成。','']
(ROOT/'ROUND18_RESULTS.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'factors':len(factors),'strategies':len(strategies),'pending_batches':pending,'pending_single_runs':pending_single,'selected_outstanding':await_strategy,'year_pass':passed}))
