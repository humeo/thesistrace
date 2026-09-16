"""Render the newly explored signals with all observed negative controls."""
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

BASE=Path(__file__).resolve().parent
records=[json.loads(p.read_text()) for p in (BASE/'results').glob('*.json')]
byid={r['run']['id']:r for r in records}
new=[r for r in records if r['run']['name'].startswith(('QS13 ','QS14 ','QS15 '))]
strategies=[r for r in new if 'summary' in r]
strategies.sort(key=lambda r:(r['run']['input']['start_date'],r['run']['name']))
factor_ids=['run_554fb58546b746199ece','run_c7887afceb5a48c18dee','run_938881bcf9fa4ca9a218',
            'run_2235fb65aad74b129f19','run_decb166e6248430b8354','run_8955849ca2264900b777']
def pc(x):return f'{x:.2%}'
lines=['# 新信号、价量择时与尾部对照','',
       '更新：'+datetime.now(timezone.utc).isoformat(),'',
       '**新增价量择时的一年期原生候选，但10万元、近期、三年和频率邻居均不支持当前投入。** WQ006开盘价/成交量负相关加MA20强市宽度门控，20只/10日的原生一年期Sharpe为1.480；三年Sharpe降至0.525、回撤23.42%，超过用户上限。它的信号不同于低成交额，市场状态规则相同；不能把参数或状态变体当作完全独立的收益来源。','',
       '线上策略固定1000万元，区间终值为2026-09-09开盘；10万元独立回放止于2026-08-27。用户目标仍为100000元、不加杠杆、最大回撤目标20%、Sharpe>1.2。模型收益不能承诺未来亏损封顶。','',
       '## 六个新公式的初筛','',
       '分属日夜收益分解、收盘位置、非流动性、年度高点附近等方向；低隔夜风险仍是防御风险的成分分解。因子Rank IC与分组收益不等于组合Sharpe。下面每个公式均为同一年期、TOP3000、none。分组收益未计交易费用，按每日信号的重叠持有标签求平均。','',
       '|信号|1日Rank IC|5日Rank IC|20日Rank IC|20日q1|20日q5|','|---|---:|---:|---:|---:|---:|']
for rid in factor_ids:
    r=byid[rid];h=r['factor']['factor']['horizons'];s=h['20']['summary']
    lines.append(f'|[{r["run"]["name"]}](https://thesistrace.com/research-runs/{rid})|{h["1"]["summary"]["rank_ic"]["mean"]:.3f}|{h["5"]["summary"]["rank_ic"]["mean"]:.3f}|{s["rank_ic"]["mean"]:.3f}|{pc(s["quantile_returns"]["q1"])}|{pc(s["quantile_returns"]["q5"])}|')
lines += ['', '隔夜均值的三个期限IC与q5均为正，因此转入实际策略检验。日内均值和收盘位置出现负向排序关系，之后检验反向规则并保留原方向。年度高点附近虽然q5为正，IC为负且q4更高，不按单一指标直接判定可交易。','',
          '这些是探索性日频改写。原论文的市场、信号时点、持有期或多空构造与这里不同；没有把分钟级隔夜预测论文当作20日做多策略的收益证据。[一手文献核查](ROUND13_SOURCES.md)。','',
          '## 已完成的实际交易结果','',
          '所有行均扣平台费用。本金1000万元，净收益为区间累计值，不是年化值。频率邻居和固定90%分位对照保留；仍在运行的项目另列，不假定结果。','',
          '|规则与参数|起点|净收益|最大回撤|Sharpe|费用拖累|','|---|---|---:|---:|---:|---:|']
for r in strategies:
    run=r['run'];m=r['summary']['metrics']
    assert float(r['summary']['initial_cash_cny'])==10000000
    assert r['provenance']['data']['generation_id']=='17f5694f6a9d47b915ffde326928b919a55181e75a4908cb661934850ac8c983'
    lines.append(f'|[{run["name"]}](https://thesistrace.com/research-runs/{run["id"]})|{run["input"]["start_date"]}|{pc(m["net_cumulative_return"])}|{pc(m["maximum_drawdown"]["value"])}|{m["sharpe"]:.3f}|{pc(m["transaction_costs"]["return_drag"])}|')
lines += ['', '分组q5约覆盖最高20%的股票，而实际策略取极端10/20只，并且只在指定调仓日产生交易。隔夜q5为正但极端Top20亏损，不能单凭这组对比把差异全归因于尾部或手续费。固定90%分位的对照把隔夜策略从亏损变为盈利，但Sharpe仍低且回撤超过20%；不继续搜索最优分位。','',
          '## 新候选的10万元回放','',
          '保持价量强市规则、20只/10日；全部止于2026-08-27。板块权限筛选、每笔额外10bp成本从真实成交与资金可负担量中计算，没有事后从收益直接相减。','',
          '|本金|范围|每笔额外成本|净收益|最大回撤|Sharpe|平均现金|','|---|---|---:|---:|---:|---:|---:|']
audit=json.loads((BASE/'capital-replay-audit.json').read_text())
wq=[r for r in audit if r['key']=='wq006_strong_h20r10']
for r in sorted(wq,key=lambda r:(-r['capital'],r['board'],r['extra_cost_bps'])):
    lines.append(f'|{r["capital"]:,.0f}|{r["board"]}|{r["extra_cost_bps"]}bp|{pc(r["net_return"])}|{pc(r["max_drawdown"])}|{r["sharpe"]:.3f}|{pc(r["mean_cash_ratio"])}|')
lines += ['', '新增1000万元对照的232个共同历史Session逐日净值与线上完全相同；本地终值日因终值政策不同被明确排除。三个10万元情景与该对照的现金、持仓单位、费用和净值独立核验通过，使用产品的合成总收益结算模型，不是完整券商现金/分红税费账本。','',
          '10万元基础情景平均现金约78.28%，1000万元约66.17%。小本金下的可成交数量和费用会改变结果，不能用原生20.60%收益直接推算个人账户。详细边界见[资本回放报告](CAPITAL_REPLAY.md)。','',
          '## 数值与样本边界','',
          '隔夜Top10一年期净收益-4.49%但Sharpe为+0.152，已独立复算。这段路径的算术日均收益约+0.0299%、日收益标准差约3.135%，平均对数收益约-0.0190%；正的算术均值与亏损的复利结果可以同时出现，不是直接的计算错误证据。[数值诊断](overnight-risk-diagnostic.json)。']
obs={}
for rid in ['run_8fedee28b1d84c1ebd4b','run_ec334d7e6ddd464f806e']:
    data=json.loads((BASE/'observations'/f'{rid}.json').read_text())
    assert data['next_cursor'] is None
    obs[rid]={b['session']:float(b['net_nav'])/float(a['net_nav'])-1 for a,b in zip(data['items'],data['items'][1:])}
days=sorted(set.intersection(*(set(r) for r in obs.values())))
corr=statistics.correlation(*[[values[d] for d in days] for values in obs.values()])
lines += [f'','价量强市20只/10日与低成交额强市20只/10日的一年期日收益相关系数约'+f'{corr:.3f}。这是共享已观察市场状态下的描述统计，不是组合账户回测或未来分散效果保证。','',
          '全部区间与这些公式都参与了探索；后续三年、季度和邻居检查不能冒充未接触的样本外。文献、因子方向、原生收益、实际本金结果均分开记录。','',
          '## 产品问题与待续工作','',
          '[产品问题10](product-audit/issues/10-factor-tail-diagnostics.md)补充了q5与极端TopN的真实落差；[问题01](product-audit/issues/01-capital-and-account-constraints.md)补充本金适配证据。没有修改或部署产品实现。','',
          '原始计划：[Round13](round13-plan.json)、[Round14](round14-plan.json)、[Round15](round15-plan.json)、[候选的后续验证](round15-followup-plan.json)。']
active=[json.loads(p.read_text()) for p in (BASE/'batches').glob('*.json')]
active=[b for b in active if b['status'] in {'queued','running','cancelling'}]
for b in active:
    lines.append(f'- 仍在执行：`{b["id"]}`，{b["status"]}；保留原ID继续查询。')
lines += ['', '最新日10万元回放仍缺数据授权：自动审批拒绝约80MB远端原始行情复制到本地指定目录，尚待明确答复。没有重新传输、拆分或绕路；用户板块权限问题也仍待回复。','']
(BASE/'NEW_SIGNALS.md').write_text('\n'.join(lines))
print(json.dumps({'new_strategy_results':len(strategies),'new_factor_cases':len(factor_ids),'wq_capital_runs':len(wq),'native_same_gate_daily_correlation':corr,'report':'NEW_SIGNALS.md'}))
