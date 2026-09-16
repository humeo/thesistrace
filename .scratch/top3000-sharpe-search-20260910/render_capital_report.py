"""Build the small-capital findings from independently audited experiment rows."""
import json
from datetime import datetime,timezone
from pathlib import Path
BASE=Path(__file__).resolve().parent
rows=json.loads((BASE/'capital-replay-audit.json').read_text())
small=[r for r in rows if r['capital']==100000]
controls=[r for r in rows if r['capital']==10000000]
records=[json.loads(p.read_text()) for p in (BASE/'results').glob('*.json')]
native_count=sum('summary' in r for r in records)
gate=[r for r in small if r['key']=='lowamount_none_h10r10' and r['market_gate']=='breadth20']
names={'lowamount_none_h10r10':'低成交额','lowamount_ind_h20r10':'低成交额/行业处理',
       'downside_ind_h10r10':'低下行波动/行业处理','lowvol_none_h100r10_quarter':'低波动/季度'}
def pc(x):return f'{x:.2%}'
def tab(items,header,format_row):
    return [header,'|'+'|'.join('---' for _ in range(header.count('|')-1))+'|']+[format_row(r) for r in items]+['']

lines=['# 10万元本金：市场状态切换与小账户回放','',
       '更新：'+datetime.now(timezone.utc).isoformat(),'',
       '**已找到10万元下的阶段性候选，尚未证明当前能稳定满足高收益与20%回撤约束。** 原有“低成交额选股＋弱市现金”的两个配置在一年期达标；新增弱市转低波动股票的10只/5日配置提高收益，但三年大本金回撤超过20%。全部保留成本、近期、权限与调仓起点差异，见[连续账户切换](MARKET_SWITCH.md)。','',
       '独立10万元回放使用100,000元初始本金，另保留1000万元对照；数据止于**2026-08-27**，不能写成9月9日。账户仍使用产品既定的合成总收益结算，未完整复现券商股息、税费和公司行动。详细边界见[CAPITAL_VALIDATION_SCOPE.md](CAPITAL_VALIDATION_SCOPE.md)。','',
       f'本轮共{len(rows)}个离线模型回放，其中{len(small)}个10万元情景、{len(controls)}个1000万元对照。现金、费用、持仓单位和净值独立核验通过。另有{native_count}个已采集的线上策略结果，使用1000万元本金；两类数量分开统计。','',
       '更新：已利用当前公开公式表达排除自身的市场宽度择时，并完成截至9月9日的线上验证。两项候选在本地共同区间的10万元逐日结果和账本与此前手动宽度规则完全相同；这种相同只对已验证的区间和调仓日成立。完整对照见[MARKET_TIMING.md](MARKET_TIMING.md)。','',
       '## 候选的具体规则','',
       '1. 股票池为每日20日平均成交额排名的TOP3000；不是市值前3000。','2. 选股公式`-rank(ts_mean(amount,20))`：在该池中优先选择过去20日平均成交额较低的股票，等权目标。',
       '3. 每个原定调仓信号日收盘，统计当前TOP3000成员中具有完整20个收盘价的股票，收盘高于各自20日均线的比例。比例≥50%时保留选股目标，否则目标为空。',
       '4. 下一交易日开盘执行，保留连续持仓、现金、整手限制、最低佣金与停牌/涨跌停拒单。市场转弱时只在既定调仓日退出，不是每日止损。',
       '5. 全板块情景允许平台覆盖的沪深主板、创业板与科创板。用户实际权限尚未确认。','',
       '## 同一年期的两项候选','',
       '区间均为2025-09-10至2026-08-27；本金10万元；费用外再扣每笔成交金额的10bp。下列配置是在已查看的同一数据上筛出的相关变体，不是两个独立Alpha。','']
selected=[r for r in gate if r['board']=='all' and r['extra_cost_bps']==10 and r['start']=='2025-09-10' and (r['holdings'],r['rebalance']) in {(10,5),(20,10)}]
lines+=tab(selected,'|配置|区间净收益|模型盈利/元|最大回撤|Sharpe|总成本/元|',lambda r:f'|{r["holdings"]}只 / {r["rebalance"]}日调仓|{pc(r["net_return"])}|{r["net_profit_cny"]:,.0f}|{pc(r["max_drawdown"])}|{r["sharpe"]:.3f}|{r["fees_cny"]:,.0f}|')
lines += ['## 近期独立建仓与账户限制','',
          '每行都重新从10万元建仓，沿自己的起点安排调仓；不是从同一历史净值截取区间。均含额外10bp成本。','']
recent=[r for r in gate if r['board']=='all' and r['extra_cost_bps']==10 and r['start']!='2025-09-10']
recent.sort(key=lambda r:(r['holdings'],r['rebalance'],r['start']))
lines+=tab(recent,'|持仓/调仓|重新建仓日|结束日|净收益|最大回撤|Sharpe|',lambda r:f'|{r["holdings"]}/{r["rebalance"]}|{r["start"]}|{r["end"]}|{pc(r["net_return"])}|{pc(r["max_drawdown"])}|{r["sharpe"]:.3f}|')
main=[r for r in gate if r['board']=='main' and r['extra_cost_bps']==10]
lines+=tab(main,'|仅主板配置|区间|净收益|最大回撤|Sharpe|',lambda r:f'|{r["holdings"]}只/{r["rebalance"]}日|{r["start"]}—{r["end"]}|{pc(r["net_return"])}|{pc(r["max_drawdown"])}|{r["sharpe"]:.3f}|')
main_chinext=[r for r in gate if r['board']=='main_chinext' and r['extra_cost_bps']==10]
lines+=tab(main_chinext,'|主板＋创业板配置|区间|净收益|最大回撤|Sharpe|',lambda r:f'|{r["holdings"]}只/{r["rebalance"]}日|{r["start"]}—{r["end"]}|{pc(r["net_return"])}|{pc(r["max_drawdown"])}|{r["sharpe"]:.3f}|')
lines+=['以上仅为权限情景，没有推断用户已开通对应板块。[官方规则与账户边界](BOARD_PERMISSIONS.md)。','']
lines += ['## 参数敏感性与未通过的结果','',
          '以下保持同一年期、同一本金和额外10bp成本。20日调仓转为亏损，说明并非任意调仓节奏都有效；不能只报最好的一行。','']
neighbors=[r for r in gate if r['board']=='all' and r['extra_cost_bps']==10 and r['start']=='2025-09-10']
neighbors.sort(key=lambda r:(r['holdings'],r['rebalance']))
lines+=tab(neighbors,'|持仓/调仓|净收益|最大回撤|Sharpe|平均现金比例|',lambda r:f'|{r["holdings"]}/{r["rebalance"]}|{pc(r["net_return"])}|{pc(r["max_drawdown"])}|{r["sharpe"]:.3f}|{pc(r["mean_cash_ratio"])}|')
lines += ['同样的择时套在低下行波动策略上，基础成本情景亏损约0.94%，加10bp后亏损约2.35%。状态切换并不自动改善所有信号。','',
          '## 为什么原1000万元预筛不能直接缩放','',
          '以下是保留原参数的10万元回放，不使用组合择时；前三项为2025-09-10起，低波动季度为2026-06-11起，均止8月27日。','']
base=[r for r in small if r['market_gate']=='none' and r['board']=='all' and r['extra_cost_bps']==0]
lines+=tab(base,'|策略|起点|收益|最大回撤|Sharpe|平均现金比例|',lambda r:f'|{names[r["key"]]}|{r["start"]}|{pc(r["net_return"])}|{pc(r["max_drawdown"])}|{r["sharpe"]:.3f}|{pc(r["mean_cash_ratio"])}|')
lines += ['100只低波动组合在10万元下平均近一半资金留在现金，主要受最小交易数量影响。20只低成交额行业处理组合从1000万元对照的约20.09%收益降到10万元的约4.09%，平均现金约29.85%。这些不是把大账户收益乘以0.01得到的数字。','',
          '## 后续价量信号候选的小资金验证','',
          'WQ006开盘价/成交量负相关信号加MA20强市宽度门控，原生一年期20只/10日达到Sharpe1.480。下面保持相同规则，以10万元重新回放至8月27日；尚未验证为适合当前投入的策略。','']
wq=[r for r in small if r['key']=='wq006_strong_h20r10']
lines+=tab(wq,'|板块范围|每笔额外成本|收益|最大回撤|Sharpe|平均现金比例|',lambda r:f'|{r["board"]}|{r["extra_cost_bps"]}bp|{pc(r["net_return"])}|{pc(r["max_drawdown"])}|{r["sharpe"]:.3f}|{pc(r["mean_cash_ratio"])}|')
lines+=['10万元基础情景平均现金约78.28%，同区间1000万元对照约66.17%；本金与最小成交数量影响不能被收益线性缩放替代。额外成本和仅主板情景也未达到Sharpe1.2。完整策略、近期与频率对照见[NEW_SIGNALS.md](NEW_SIGNALS.md)。','',
          '## 验证与仍缺的证据','',
          f'- {len(controls)}个大本金控制与线上共同历史逐日净值完全一致；独立核验逐日现金、结算、费用、持仓和净值，见[审计CSV](capital-replay-audit.csv)。',
          '- 采用真实行情和实际100000元参数，但模型不是完整券商账户；合成结算调整需与原始成交金额区别。[产品问题11](product-audit/issues/11-synthetic-account-and-settlement.md)。',
          '- 现有结果经过多次探索，存在后验筛选偏差；最近区间和参数验证不能冒充未看过的样本外。尚无真实资金业绩，也未验证2018年以来该组合择时的完整周期。',
          '- 每笔额外10bp只是成本压力情景，未覆盖部分成交、全部盘口冲击和真实税费。历史最大回撤低于20%不能保证未来最大亏损。',
          '- 线上9月9日的局部行情导出仍等待明确授权：自动审批审核因缺少数据载荷及本地目的地授权拒绝了约80MB复制，未执行或绕过。',
          '- 用户板块权限问题仍待回复；主板情景与全板块结果分开列出。','',
          '实验输入：[现金切换规则](market-gate-plan.json)、[邻近参数计划](market-gate-sensitivity-plan.json)、[近期与权限验证计划](selected-recent-plan.json)。原始输出保存在`capital-replay/`，每个文件含本金、公式、参数、源快照、成交、持仓和逐日账本。','',
          '[产品问题总表](product-audit/REPORT.md)现为11项；本轮没有修改或部署产品代码。']
(BASE/'CAPITAL_REPLAY.md').write_text('\n'.join(lines)+'\n')

regimes=[r for r in records if 'summary' in r and r['run']['name'].startswith('QS4 ')]
regimes.sort(key=lambda r:r['run']['name'])
rl=['# 固定窗口中的个股状态切换结果','',
    'QS4全部9个个股规则/时间段与3个静态一年期对照已完成。均为TOP3000、100只、每20日调仓、1000万元本金，止于2026-09-09；这些是单个股票评分切换，不是组合转现金。没有一项Sharpe>1.2。','',
    '|策略与区间|起点|净累计收益|最大回撤|Sharpe|','|---|---|---:|---:|---:|']
for r in regimes:
    run=r['run'];m=r['summary']['metrics']
    rl.append(f'|[{run["name"]}](https://thesistrace.com/research-runs/{run["id"]})|{run["input"]["start_date"]}|{pc(m["net_cumulative_return"])}|{pc(m["maximum_drawdown"]["value"])}|{m["sharpe"]:.3f}|')
rl+=['','后续现金/股票切换已在独立10万元模型中回放，见[CAPITAL_REPLAY.md](CAPITAL_REPLAY.md)。现有公开rank公式还可表达特定的排除自身市场宽度择时，已通过原生MCP验证，见[MARKET_TIMING.md](MARKET_TIMING.md)；仍缺直接的市场状态与多策略组合接口。']
(BASE/'REGIME_RESULTS.md').write_text('\n'.join(rl)+'\n')
print(json.dumps({'capital_report':'CAPITAL_REPLAY.md','audited_runs':len(rows),'selected_same_family_configs':len(selected),'qs4_rows':len(regimes)}))
