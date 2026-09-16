"""Summarize current native market-timing research without mixing capital scopes."""
import csv
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
records = [json.loads(p.read_text()) for p in (BASE/'results').glob('*.json')]
selected = [r for r in records if 'summary' in r and r['run']['name'].startswith(('QS10 ', 'QS11 ', 'QS12 '))]
selected.sort(key=lambda r: (r['run']['input']['start_date'], r['run']['name']))
def pc(x): return f'{x:.2%}'
capital_audit = json.loads((BASE/'capital-replay-audit.json').read_text())
small_capital_count = sum(r['capital'] == 100000 for r in capital_audit)
def st(xs):
    nav = peak = 1.0
    dd = 0.0
    for x in xs:
        nav *= 1+x
        peak = max(peak, nav)
        dd = max(dd, 1-nav/peak)
    sd = statistics.stdev(xs)
    return {'net_return': nav-1, 'sharpe': statistics.fmean(xs)/sd*math.sqrt(252) if sd else None, 'dd': dd}

lines = ['# 最新日市场宽度择时：原生MCP与10万元证据', '',
         '更新：'+datetime.now(timezone.utc).isoformat(), '',
         '**目前找到的是同一低成交额家族中的阶段性候选，尚未证明适合现在投入10万元。** 用户要求为不加杠杆、本金100000元、最大回撤目标20%、Sharpe严格大于1.2。', '',
         f'本页线上策略全部固定1000万元，终值为2026-09-09开盘；累计{small_capital_count}项10万元模型情景止于2026-08-27，详见[小账户报告](CAPITAL_REPLAY.md)。不能把两类结果合并或按资金比例缩放。所有区间已参与探索，不是未看过的样本外。', '',
         '## 已实现的切换规则', '',
         '在TOP3000内按20日平均成交额从低到高选择10或20只，等权目标。每个原定调仓日收盘，检查其他有效成员中高于各自均线的比例；达到50%才保留候选，否则排除。若没有候选，下一交易日开盘尝试清仓；未到调仓日继续持有原组合。停牌与涨跌停仍可能阻碍成交。这不是20%的硬止损。', '',
         '20日/60日/120日是观察市场宽度的均线长度；5日/10日是调仓间隔。延长均线还会改变新股或历史缺失股票的有效样本，因此加入具有120日完整历史要求的静态选股对照。60日版本与此对照不具有完全相同的样本要求。', '',
         'QS12另行检验弱市低波动：其他有效成员的MA20上方比例严格低于50%时，选择低波动股票，其他时间持币。它与强市门控在有效样本上互补；本地233日共466个门控/日期检查通过独立整数计数验证。[预先记录计划](round12-plan.json)与[公式检查](weak-breadth-proof.json)。这不是在弱市买入必然赚钱的假设。', '',
         '公式使用当前公开rank语义。对二值b与n>1，`1+b_i-2*rank(b)_i = (sum(b)-b_i)/(n-1)`。它是排除自身后的宽度，临界日并非全组合统一开关。完整输入见[20日公式](loo-breadth-plan.json)和[60/120日预先记录计划](round11-plan.json)。', '',
         '## 全部已完成结果', '',
         '均含平台默认费用，不含离线每笔额外10bp成本。下面的收益是区间累计值，不是年化值。', '',
         '|策略与参数|起点|净收益|最大回撤|Sharpe|平均现金比例|',
         '|---|---|---:|---:|---:|---:|']
for r in selected:
    run=r['run']; m=r['summary']['metrics']
    assert float(r['summary']['initial_cash_cny']) == 10000000
    lines.append(f'|[{run["name"]}](https://thesistrace.com/research-runs/{run["id"]})|{run["input"]["start_date"]}|{pc(m["net_cumulative_return"])}|{pc(m["maximum_drawdown"]["value"])}|{m["sharpe"]:.3f}|{pc(m["cash_ratio"]["mean"])}|')

focus=['run_e20c03fe0028468799de','run_ec334d7e6ddd464f806e']
by_id={r['run']['id']:r for r in records}
lines += ['', '## 近期路径与调仓起点', '',
          '以下从一年期连续净值截取2026-06-11之后的收益，保留原持仓和调仓节奏；与同日重新建仓的季度回测不同。这些切片不计作新的达标策略。', '',
          '|一年期原策略|连续路径季度收益|连续路径季度Sharpe|局部最大回撤|9月9日持仓数|9月9日现金比例|',
          '|---|---:|---:|---:|---:|---:|']
for rid in focus:
    r=by_id[rid]; obs=json.loads((BASE/'observations'/f'{rid}.json').read_text())['items']
    xs=[float(b['net_nav'])/float(a['net_nav'])-1 for a,b in zip(obs,obs[1:]) if b['session']>'2026-06-11']
    s=st(xs); last=obs[-1]
    lines.append(f'|{r["run"]["name"]}|{pc(s["net_return"])}|{s["sharpe"]:.3f}|{pc(s["dd"])}|{last["holdings_count"]}|{pc(float(last["net_cash"])/float(last["net_nav"]))}|')
lines += ['', '上述现金与持仓是各自历史回测路径在终值时的状态，不是现在账户的交易指令，也不是9月9日收盘信号。每5日与每10日的策略当日可以一条持股、一条空仓。', '',
          '一年期两项20日低成交额候选的日收益相关系数约0.433；242个观察日中分别只有96和90日持股。它们虽非完全同步，仍属于同一经济信号家族；这些数值不是组合账户回测。[路径依赖记录](loo-family-dependence.json)。', '',
          '## 10万元等价检查与统计不确定性', '',
          '- 对n=2至100的5148个二值分布验证了rank恒等式。本地233个Session的原生公式逐股结果与独立排除自身计数一致；与整体宽度有1个临界日差异（2025-09-12），该日不在两项候选的调仓信号日上。[公式证据](loo-breadth-proof.json)。',
          '- 在2025-09-10至2026-08-27、10万元、每笔额外10bp的共同区间，10只/5日与20只/10日的原生表达式和手动宽度规则，逐日净值、持仓、成交、费用与完整账本完全一致。未将这两项等价检查计作新的经济假设。[对账证据](loo-capital-equivalence.json)。',
          '- 四条20日低成交额的一年/三年原生路径已经完整分页并独立复算Sharpe及最大回撤，误差小于1e-8。',
          '- 一年期与三年期差异、季度新建仓以及主板权限情景都必须保留。2项一年期配置不代表2个独立Alpha。']
boot=list(csv.DictReader((BASE/'sharpe-resampling.csv').open()))
boot=[r for r in boot if r['run_id'] in focus and r['block_sessions']=='10']
if boot:
    lines += ['', '|一年期配置|原Sharpe|10日块重采样2.5%分位|97.5%分位|', '|---|---:|---:|---:|']
    for r in boot:
        lines.append(f'|{r["name"]}|{float(r["point_sharpe"]):.3f}|{float(r["q025"]):.3f}|{float(r["q975"]):.3f}|')
    lines += ['', '固定种子、每组2000次循环区块重采样；这是已观察净收益的经验分位范围，不能解释成未来真实Sharpe的置信保证或超过1.2的概率，未校正挑选赢家偏差。[完整诊断](SHARPE_UNCERTAINTY.md)。']
lines += ['', '## 产品记录与下一步', '',
          '现有DSL已能表达上述特定择时，已修正此前“完全缺乏组合择时”的判断。仍缺直接的状态/目标现金接口、便于对照的多时间段研究，以及用户本金和账户权限配置。另记录了两个Strategy Sweep拒绝而等价单Run成功的容量诊断差异。[11项问题记录](product-audit/REPORT.md)。', '',
          '尚待确认用户板块权限。最新远端原始行情约80MB导出到本研究目录的操作被自动审批拒绝，原因是缺少对具体载荷与本地目的地的明确授权；尚未执行，仍待用户审批。原生MCP研究可独立继续，但结果本金仍为1000万元。', '']
active=[]
for p in (BASE/'batches').glob('*.json'):
    b=json.loads(p.read_text())
    if b['status'] in {'queued','running','cancelling'}:
        active.append(b)
if active:
    lines += ['本页只列出已完成结果，仍在执行的批次：','']
    for b in active:
        lines.append(f'- `{b["id"]}`：{b["status"]}，区间{b["scope"]["start_date"]}至{b["scope"]["end_date"]}。')
    lines.append('')
(BASE/'MARKET_TIMING.md').write_text('\n'.join(lines))
print(json.dumps({'completed_native_timing_or_control_runs':len(selected),'report':'MARKET_TIMING.md'}))
