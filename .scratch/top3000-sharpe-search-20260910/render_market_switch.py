"""Render the controlled market-score switch and its real-capital scenarios."""
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

BASE=Path(__file__).resolve().parent
records=[json.loads(p.read_text()) for p in (BASE/'results').glob('*.json')]
native=[r for r in records if r['run']['name'].startswith('QS16 ')]
native.sort(key=lambda r:(r['run']['input']['start_date'],r['run']['name']))
audit=json.loads((BASE/'capital-replay-audit.json').read_text())
small=[r for r in audit if r['capital']==100000 and r['key'].startswith('switch_amount_lowvol_')]
controls=[r for r in audit if r['capital']==10000000 and r['key'].startswith('switch_amount_lowvol_')]
proof=json.loads((BASE/'market-switch-proof.json').read_text())
byid={r['run']['id']:r for r in native}
def pc(x):return f'{x:.2%}'
lines=['# 强市低成交额、弱市低波动：连续账户切换','',
       '更新：'+datetime.now(timezone.utc).isoformat(),'',
       '**切换规则的部分区间收益较高，但调仓邻近检验未通过。** 4/6/9/11日四个邻近配置均不能同时通过全年和季度，见[调仓敏感性](SWITCH_NEIGHBORS.md)。10只/5日的小资金一年与近期全板块情景达标，三年原生回撤却为25.12%；20只/10日的三年原生Sharpe1.209、回撤16.50%，小资金加成本后Sharpe不足1.2。原生止于2026-09-09开盘，独立100000元回放止于2026-08-27；全部时间段参与探索，均非未接触的样本外。','',
       '## 完整规则与对照','',
       '在每日按20日成交额均值划定的TOP3000内，收盘计算其他有效成员高于自身20日均线的比例。达到50%时用低20日成交额评分，否则用低20日日收益波动评分；按照当日评分选择10或20只，目标等权。每5或10个交易日调仓一次，最早下日开盘执行。未到调仓日维持连续持仓。','',
       '这是一个账户中的评分切换，弱市继续持有股票；不保证弱市赚钱或最大亏损被限制在20%。同一股票的两种评分必须同时有效，缺失的非活动分支也会排除该股票。现金对照使用完全相同的共同历史要求，只在强市选低成交额、弱市转现金。','',
       f'独立核对{proof["session_count"]}个本地交易日、{proof["score_checks"]:,}个评分，最大误差{proof["maximum_score_error"]:.2g}。额外共同历史排除{proof["amount_eligibility_removed_by_common_validity"]}个股票/日期样本；2025-09-12是排除自身后不同股票可能落入不同状态的临界日。这不是严格的全组合统一开关。[公式证据](market-switch-proof.json)。','',
       '两项现金对照各242个原生观察与原先现金策略一致，比较了净值、现金、费用、持仓数/集中度与拒单计数；未据此声称持仓名册完全相同。[对照证据](round16-control-equivalence.json)。两个对照不新增独立经济信号。','',
       '## 原生1000万元结果','',
       '收益为各区间累计净收益；全部截止2026-09-09。','',
       '|规则与参数|开始日|净收益|最大回撤|Sharpe|平均现金|','|---|---|---:|---:|---:|---:|']
for r in native:
    m=r['summary']['metrics'];run=r['run'];assert float(r['summary']['initial_cash_cny'])==10000000
    lines.append(f'|[{run["name"]}](https://thesistrace.com/research-runs/{run["id"]})|{run["input"]["start_date"]}|{pc(m["net_cumulative_return"])}|{pc(m["maximum_drawdown"]["value"])}|{m["sharpe"]:.3f}|{pc(m["cash_ratio"]["mean"])}|')
long=[r for r in native if r['run']['input']['start_date']=='2023-09-11']
if len(long)==2:
    passed=sum(r['summary']['metrics']['sharpe']>1.2 and r['summary']['metrics']['maximum_drawdown']['value']<=0.2 for r in long)
    lines += ['',f'三年两项均已采集，同时满足Sharpe>1.2与回撤≤20%的有{passed}项。不能用一年或季度通过覆盖三年未通过的结果。']
lines += ['', '## 10万元实际参数回放','',
          '下表全部经过独立账本核验，止于2026-08-27。all为平台全部沪深板块；main为仅主板；main_chinext为主板与创业板。用户权限尚待确认，均为条件情景。[权限依据与边界](BOARD_PERMISSIONS.md)。','',
          '|起点|持仓/调仓|板块|额外每笔成本|净收益|模型盈利/元|最大回撤|Sharpe|总成本/元|','|---|---|---|---:|---:|---:|---:|---:|---:|']
for r in sorted(small,key=lambda r:(r['start'],r['holdings'],r['board'],r['extra_cost_bps'])):
    lines.append(f'|{r["start"]}|{r["holdings"]}/{r["rebalance"]}|{r["board"]}|{r["extra_cost_bps"]}bp|{pc(r["net_return"])}|{r["net_profit_cny"]:,.0f}|{pc(r["max_drawdown"])}|{r["sharpe"]:.3f}|{r["fees_cny"]:,.0f}|')
lines += ['', '## 与弱市现金的同本金比较','',
          '均为10万元、2025-09-10至2026-08-27、10只/5日、每笔额外10bp。两个模型的目标状态不同，直接比较完整账户净结果；没有把独立策略净值相加。','',
          '|板块|弱市配置|净收益|最大回撤|Sharpe|总成本/元|','|---|---|---:|---:|---:|---:|']
for board in ['all','main_chinext','main']:
    for key,gate,label in [('lowamount_none_h10r10','breadth20','现金'),('switch_amount_lowvol_h10r5','authored_market_switch_breadth20','低波动股票')]:
        rows=[r for r in audit if r['capital']==100000 and r['key']==key and r['board']==board and r['market_gate']==gate and r['holdings']==10 and r['rebalance']==5 and r['start']=='2025-09-10' and r['extra_cost_bps']==10]
        for r in rows:lines.append(f'|{board}|{label}|{pc(r["net_return"])}|{pc(r["max_drawdown"])}|{r["sharpe"]:.3f}|{r["fees_cny"]:,.0f}|')
lines += ['', '持股切换可以提高累计收益，同时增加费用和回撤；不能简单认为收益更高就比持现金全面更优。主板＋创业板的一年期切换Sharpe仅略高于1.2，而近期小资金情景未必通过，必须同时看。[同一账户状态损益与费用归因](REGIME_ACCOUNT_ATTRIBUTION.md)。','',
          '## 连续一年路径的近期切片','',
          '下面保留原一年期的持仓和调仓相位，以2026-06-11开盘净值为基点；与季度新建仓不同。仅为原生1000万元路径诊断。','',
          '|原一年期配置|切片净收益|切片Sharpe|切片内回撤|终值持仓数|','|---|---:|---:|---:|---:|']
for rid in ['run_c9871f3c547147bc80a1','run_fe6c5b6b5f2d4a2395da']:
    obs=json.loads((BASE/'observations'/f'{rid}.json').read_text())['items']
    values=[float(r['net_nav']) for r in obs if r['session']>='2026-06-11']
    xs=[b/a-1 for a,b in zip(values,values[1:])];peak=values[0];dd=0
    for v in values:peak=max(peak,v);dd=max(dd,1-v/peak)
    sh=statistics.fmean(xs)/statistics.stdev(xs)*math.sqrt(252)
    lines.append(f'|{byid[rid]["run"]["name"]}|{pc(values[-1]/values[0]-1)}|{sh:.3f}|{pc(dd)}|{obs[-1]["holdings_count"]}|')
lines += ['', '终值持仓数是历史路径状态，不是今日交易指令。','',
          '## 验证边界与证据','',
          f'- 新增{len(controls)}个大本金对照的共同历史净值与原生逐日完全匹配；{len(small)}个10万元切换情景独立核对现金、费用、持仓单位、净值及板块资格。会计仍是产品合成总收益模型，不是完整券商股息/税费账本。',
          '- 初次朴素NumPy逐股均线与当前补偿求和在39个恰等于均线的显示值样本处发生二值差异；保留失败与诊断证据。所有最终市场状态与独立计数一致，没有放宽最终评分或状态断言，也未修改公式。[数值诊断](round16-diagnosis.json)。',
          '- 额外10bp为每笔成交成本压力，参与实际可负担股数和逐日现金计算；未模拟完整盘口冲击或部分成交。',
          '- 最新远端约80MB原始行情复制尚待明确授权，自动审批已拒绝该具体传输；未执行或绕路。小资金日期没有延伸至9月9日。',
          '- 现有指标受到研究筛选和区间选择影响，短期Sharpe不代表稳定未来收益。暂无真实资金业绩。','',
          '计划与原始记录：[Round16](round16-plan.json)、[三年及季度验证](round16-followup-plan.json)、[近期小资金](round16-capital-quarter-plan.json)、[账本核验](capital-replay-audit.csv)、[产品问题03](product-audit/issues/03-portfolio-regime-switching.md)。','']
active=[json.loads(p.read_text()) for p in (BASE/'batches').glob('*.json')]
for b in active:
    if b['status'] in {'queued','running','cancelling'}:
        lines.append(f'仍在运行：`{b["id"]}`，继续原ID查询，不重复提交。')
(BASE/'MARKET_SWITCH.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'native_results':len(native),'small_capital_runs':len(small),'controls':len(controls),'report':'MARKET_SWITCH.md'}))
