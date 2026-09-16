"""Attribute audited account P&L to preceding rebalance regime, with fees separate."""
import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path

BASE=Path(__file__).resolve().parent
audit=json.loads((BASE/'capital-replay-audit.json').read_text())
proof=json.loads((BASE/'market-switch-proof.json').read_text())
states={r['session']:r for r in proof['rows']}
selected=[r for r in audit if r['capital']==100000 and r['board']=='all' and r['extra_cost_bps']==10
          and r['start'] in {'2025-09-10','2026-06-11'} and (r['holdings'],r['rebalance']) in {(10,5),(20,10)}
          and ((r['key']=='lowamount_none_h10r10' and r['market_gate']=='breadth20')
               or r['key'].startswith('switch_amount_lowvol_'))]
output=[]
for record in selected:
    assert record['board_access_verified']
    d=json.loads((BASE/record['file']).read_text())
    assert d['source_generation']==proof['source_generation']
    switching=d['key'].startswith('switch_amount_lowvol_')
    gate={r['signal_session']:r['risk_on'] for r in d.get('market_gate_series',[])}
    def label(signal_session):
        if not switching:return 'strong_amount' if gate[signal_session] else 'weak_cash'
        r=states[signal_session]
        if r['strong_common']==0:return 'weak_lowvol'
        if r['weak_common']==0:return 'strong_amount'
        return 'mixed_boundary'
    active='initial_cash';intervals=defaultdict(int);gross=defaultdict(Decimal)
    fees_by_state=defaultdict(Decimal);fees_by_event=defaultdict(Decimal)
    event_counts=defaultdict(int);cash_sums=defaultdict(float);held_sums=defaultdict(int)
    days=d['result']['daily'];ledger=d['ledger'];assert len(days)==len(ledger)
    with localcontext() as ctx:
        ctx.prec=80
        for t,(day,book) in enumerate(zip(days,ledger)):
            assert day['session']==book['session']
            fees=Decimal(book['transaction_cost_cny'])
            if t:
                prev=days[t-1]
                pnl=Decimal(day['net_nav'])-Decimal(prev['net_nav'])+fees
                gross[active]+=pnl;intervals[active]+=1
                cash_sums[active]+=float(Decimal(prev['net_cash'])/Decimal(prev['net_nav']))
                held_sums[active]+=prev['holdings_count']
            else:assert fees==0 and Decimal(day['net_nav'])==Decimal(100000)
            signal=book['signal']
            next_state=label(signal['session']) if signal else active
            event=('initial_entry' if active=='initial_cash' else 'regime_change' if active!=next_state else 'same_regime_rebalance') if signal else 'no_rebalance'
            if signal:event_counts[event]+=1
            fees_by_state[next_state]+=fees;fees_by_event[event]+=fees
            active=next_state
        total_gross=sum(gross.values());total_fees=sum(fees_by_state.values())
        expected_profit=Decimal(days[-1]['net_nav'])-Decimal(100000)
        residual=total_gross-total_fees-expected_profit
        assert abs(residual)<Decimal('0.000001')
        assert abs(total_fees-Decimal(str(d['result']['metrics']['transaction_costs']['cumulative_amount'])))<Decimal('0.000001')
        output.append({'file':record['file'],'key':record['key'],'start':d['start'],'end':d['end'],
            'holdings':d['holdings_count'],'rebalance':d['rebalance_every_sessions'],
            'gross_pnl_cny_by_prior_target_regime':{k:str(v) for k,v in gross.items()},
            'fees_cny_by_post_trade_target_regime':{k:str(v) for k,v in fees_by_state.items()},
            'fees_cny_by_rebalance_event':{k:str(v) for k,v in fees_by_event.items()},
            'target_regime_interval_counts':dict(intervals),'rebalance_event_counts':dict(event_counts),
            'mean_prior_cash_by_regime':{k:cash_sums[k]/n for k,n in intervals.items()},
            'mean_prior_holdings_by_regime':{k:held_sums[k]/n for k,n in intervals.items()},
            'total_gross_pnl_cny':str(total_gross),'total_fees_cny':str(total_fees),
            'net_profit_cny':str(expected_profit),'account_identity_residual_cny':str(residual)})
(BASE/'regime-account-attribution.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
lines=['# 已审计10万元账户的状态收益与费用','',
       '更新：'+datetime.now(timezone.utc).isoformat(),'',
       '全部为100000元、平台全部沪深板块、默认费用再加每笔10bp、止于2026-08-27。账户口径是产品合成总收益结算。只做已发生路径的金额归因，未建立新策略或新增独立回测。','',
       '从每个开盘到下一开盘的持仓损益，归给前一个开盘处理完成后的最近一次目标状态；当日费用单独归给本次再平衡事件。用“净值变化＋当日费用”还原该段费用前持仓损益。二者相加后减总费用严格等于区间模型盈利，不将状态内条件收益当作可独立交易的Sharpe。','',
       '目标状态不保证实际持仓已完成转换；停牌或涨跌停留下的仓位仍属于当时账户路径。这不是强市/弱市造成收益的因果证明，切换会改变后续资金与再平衡，不能将独立账户的分段损益直接拼接。','',
       '|起点|持仓/调仓|弱市目标|强市目标期间持仓损益/元|弱市目标期间持仓损益/元|总成本/元|其中状态改变事件成本/元|净盈利/元|','|---|---|---|---:|---:|---:|---:|---:|']
for r in sorted(output,key=lambda r:(r['start'],r['holdings'],r['key'])):
    g=r['gross_pnl_cny_by_prior_target_regime'];e=r['fees_cny_by_rebalance_event']
    weak=sum(Decimal(v) for k,v in g.items() if k.startswith('weak_'))
    weak_label='低波动股票' if r['key'].startswith('switch_') else '现金'
    lines.append(f'|{r["start"]}|{r["holdings"]}/{r["rebalance"]}|{weak_label}|{Decimal(g.get("strong_amount","0")):,.0f}|{weak:,.0f}|{Decimal(r["total_fees_cny"]):,.0f}|{Decimal(e.get("regime_change","0")):,.0f}|{Decimal(r["net_profit_cny"]):,.0f}|')
lines+=['','每行使用自己的连续账户和调仓相位。强市持仓金额贡献也会因先前弱市收益、成本和资本变化而变化；不能把上表差异全解释为弱市因子的纯贡献。完整逐状态日期数、平均现金与换仓次数保存在[JSON证据](regime-account-attribution.json)。','',
        '来源：[独立账本核验](capital-replay-audit.csv)、[已核对的状态公式](market-switch-proof.json)、[策略及跨区间结果](MARKET_SWITCH.md)。']
(BASE/'REGIME_ACCOUNT_ATTRIBUTION.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'audited_account_paths':len(output),'all_account_pnl_identities_verified':True,'report':'REGIME_ACCOUNT_ATTRIBUTION.md'}))
