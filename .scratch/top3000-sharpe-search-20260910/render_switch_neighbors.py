"""Compare all predeclared QS17 neighbors, never selects a winning schedule."""
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent
plan=json.loads((ROOT/'round17-plan.json').read_text())
records=[json.loads(p.read_text()) for p in (ROOT/'results').glob('*.json')]
centers={'run_c9871f3c547147bc80a1','run_fe6c5b6b5f2d4a2395da','run_9a68e61b294844ab9aa7','run_7e94f022b5da43838f6f'}
rows=[r for r in records if r['run']['name'].startswith('QS17 ') or r['run']['id'] in centers]
assert len(rows)==12
def describe(values):
    returns=[b/a-1 for a,b in zip(values,values[1:])]
    peak=values[0];dd=0
    for v in values:
        assert math.isfinite(v) and v>0
        peak=max(peak,v);dd=max(dd,1-v/peak)
    return {'net_return':values[-1]/values[0]-1,'sharpe':statistics.fmean(returns)/statistics.stdev(returns)*math.sqrt(252),'max_drawdown':dd,'returns':returns}
out=[]
for r in rows:
    run=r['run'];rid=run['id'];i=run['input'];m=r['summary']['metrics']
    assert i['formula']==plan['formula'] and i['end_date']==plan['end_date']
    assert i['universe']=='top3000' and i['neutralization']=='none'
    assert float(r['summary']['initial_cash_cny'])==10000000
    assert r['provenance']['data']['generation_id']=='17f5694f6a9d47b915ffde326928b919a55181e75a4908cb661934850ac8c983'
    assert r['provenance']['data']['data_through_session']=='2026-09-09'
    obs=json.loads((ROOT/'observations'/f'{rid}.json').read_text())
    assert obs['next_cursor'] is None
    days=obs['items'];dates=[x['session'] for x in days]
    assert dates==sorted(set(dates)) and dates[0]==i['start_date'] and dates[-1]==i['end_date']
    metrics=describe([float(x['net_nav']) for x in days])
    assert abs(metrics['sharpe']-m['sharpe'])<1e-8
    assert abs(metrics['net_return']-m['net_cumulative_return'])<1e-8
    assert abs(metrics['max_drawdown']-m['maximum_drawdown']['value'])<1e-8
    recent=[x for x in days if x['session']>='2026-06-11']
    recent_metrics=describe([float(x['net_nav']) for x in recent])
    out.append({'run_id':rid,'holdings':i['holdings_count'],'rebalance':i['rebalance_every_sessions'],'start':i['start_date'],
                'end':i['end_date'],'is_previously_selected_center':rid in centers,'observations':len(days),
                **{k:v for k,v in metrics.items() if k!='returns'},
                'recent_continuous_slice':{k:v for k,v in recent_metrics.items() if k!='returns'},
                'net_fee_ratio':m['transaction_costs']['ratio'],
                'passes_native_window':m['sharpe']>1.2 and m['maximum_drawdown']['value']<=0.20})
out.sort(key=lambda r:(r['holdings'],r['rebalance'],r['start']))
paired=[]
for spec in plan['strategies']:
    group=[r for r in out if r['holdings']==spec['holdings_count'] and r['rebalance']==spec['rebalance_every_sessions']]
    assert len(group)==2
    paired.append({'holdings':spec['holdings_count'],'rebalance':spec['rebalance_every_sessions'],
                   'passes_both_windows':all(r['passes_native_window'] for r in group),
                   'run_ids':[r['run_id'] for r in group]})
assert sum(p['passes_both_windows'] for p in paired)==0
payload={'generated_at':datetime.now(timezone.utc).isoformat(),'plan':'round17-plan.json','new_run_count':8,
         'context_center_count':4,'native_initial_cash_cny':10000000,'rows':out,'paired_screen':paired,
         'new_followups':[],'interpretation':'All4 predeclared neighboring configurations fail year+quarter joint screen. Centers remain observed selected cases, not robustly qualified user strategies. Interval changes both phase and turnover.'}
(ROOT/'switch-neighbor-comparison.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
lines=['# 切换策略的调仓邻近检验','',
       '四个预先固定的邻近配置，均未同时通过全年和最近季度的 Sharpe>1.2、回撤≤20% 条件。原先5日/10日的高值仍是已观察到的结果，但其邻近频率表现不稳定，不能据此推荐10万元实盘。','',
       '公式、TOP3000、无行业中性化和默认费用相同，全部截止2026-09-09开盘。全年从2025-09-10开始，季度从2026-06-11重新建仓。原生本金仍为1000万元；两个窗口已参与研究，不是未见样本外。','',
       '|持仓数|调仓间隔/交易日|角色|全年净收益|全年回撤|全年Sharpe|季度净收益|季度回撤|季度Sharpe|同时通过|',
       '|---:|---:|---|---:|---:|---:|---:|---:|---:|---|']
for h,frequencies in [(10,[4,5,6]),(20,[9,10,11])]:
    for f in frequencies:
        a=next(r for r in out if r['holdings']==h and r['rebalance']==f and r['start']=='2025-09-10')
        b=next(r for r in out if r['holdings']==h and r['rebalance']==f and r['start']=='2026-06-11')
        role='之前选中中心' if a['is_previously_selected_center'] else '本轮邻居'
        passed='是' if a['passes_native_window'] and b['passes_native_window'] else '否'
        lines.append(f"|{h}|{f}|{role}|{a['net_return']:.2%}|{a['max_drawdown']:.2%}|{a['sharpe']:.3f}|{b['net_return']:.2%}|{b['max_drawdown']:.2%}|{b['sharpe']:.3f}|{passed}|")
lines+=['','20只/9日的季度Sharpe最高达3.300，全年却只有0.233；本轮没有据季度排名追加三年或小资金优化。改变调仓间隔同时改变交易次数、实际买卖日和状态切换时点，本轮不能将差异单独归因于费用或相位。','',
        '## 同一年度账户的最近季度切片','',
        '保留9月起的原有持仓及调仓安排，以2026-06-11开盘净值为起点。下表不是另开账户，净收益与上述季度新建仓不能混用。','',
        '|持仓/调仓|近期连续切片净收益|近期连续切片回撤|近期连续切片Sharpe|原生一年结果|',
        '|---|---:|---:|---:|---|']
for r in out:
    if r['start']!='2025-09-10':continue
    s=r['recent_continuous_slice'];rid=r['run_id']
    lines.append(f"|{r['holdings']}/{r['rebalance']}|{s['net_return']:.2%}|{s['max_drawdown']:.2%}|{s['sharpe']:.3f}|[{rid}](https://thesistrace.com/research-runs/{rid})|")
lines+=['','全部8个新结果及4个中心对照均有完整分页净值，独立复算净收益、Sharpe与回撤，误差小于1e-8。仅说明这些计算与净值一致，不证明经济稳定性。季度64个净值点、全年242个净值点。','',
        '三年与10万元方面的既有冲突仍保留：10只/5日的三年原生回撤25.12%；20只/10日的10万元全年额外10bp情景Sharpe1.055。见[切换全证据](MARKET_SWITCH.md)。','',
        '已完成预声明的8项检验，本轮不继续扫描新的调仓频率或宽度门槛。[计划](round17-plan.json)、[机器可读结果](switch-neighbor-comparison.json)、[状态费用归因](REGIME_ACCOUNT_ATTRIBUTION.md)。','']
(ROOT/'SWITCH_NEIGHBORS.md').write_text('\n'.join(lines)+'\n')
plan['status']='all_planned_results_collected_and_checked'
plan['completed_observed_at']=datetime.now(timezone.utc).isoformat()
plan['joint_passing_neighbors']=[]
plan['followup_required']=False
plan['completed_run_ids']=[r['run_id'] for r in out if not r['is_previously_selected_center']]
plan['caveats']=[x.replace('Original10kcapital','Original100kcapital') for x in plan['caveats']]
(ROOT/'round17-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'new':8,'context':4,'joint_pass':0,'report':'SWITCH_NEIGHBORS.md'}))
