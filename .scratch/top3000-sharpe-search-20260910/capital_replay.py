"""Offline research experiment on real immutable market data, NOT a product run.

Only INITIAL_CASH is scoped to a different Decimal in this separate process; no
production code or data is edited. Keep native 10m controls and ledger evidence.
"""
import argparse
import gc
import hashlib
import json
import statistics
import sys
import time
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import numpy as np

from thesistrace.alpha_language import alpha_language
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.research_kernel.alpha import evaluate_columnar_alpha_matrix, alpha_matrix_checksum
from thesistrace.research_kernel import strategy

parser = argparse.ArgumentParser()
parser.add_argument('--source', choices=['local','latest'], default='local')
parser.add_argument('--board', choices=['all','main','main_chinext'], default='all')
parser.add_argument('--extra-cost-bps', type=int, choices=[0,10], default=0)
parser.add_argument('--market-gate', choices=['none','breadth20'], default='none')
parser.add_argument('--start', choices=['2025-09-10','2026-01-05','2026-03-10','2026-06-11'])
parser.add_argument('--holdings', type=int, choices=[5,10,20])
parser.add_argument('--rebalance', type=int, choices=[5,10,20])
parser.add_argument('cases', nargs='*')
args = parser.parse_args()
BASE = Path(__file__).resolve().parent
DATA = BASE / ('latest-market' if args.source=='latest' else 'offline-market')
OUTPUT = BASE / ('capital-replay-latest' if args.source=='latest' else 'capital-replay')
OUTPUT.mkdir(exist_ok=True)
GENERATION = ('17f5694f6a9d47b915ffde326928b919a55181e75a4908cb661934850ac8c983'
              if args.source=='latest' else '4723b071313705df8662131f4ec4137e4cf35a9680a7c63c1a0191eb66e83e7f')
END = '2026-09-09' if args.source=='latest' else '2026-08-27'
COSTS = {'commission_rate_all_in':'0.0003', 'commission_min_cny':'5',
         'stamp_duty_sell_rate':'0.0005', 'transfer_fee_rate':'0.00001'}
CASES = [
    ('downside_ind_h10r10', 'run_a5d9a9582f6c44f6b39a'),
    ('lowamount_ind_h20r10', 'run_1b900ded767b4705b61e'),
    ('lowamount_none_h10r10', 'run_f87508c0fc204af1b381'),
    ('lowvol_none_h100r10_quarter', 'run_96384289b08844dca9dc'),
    ('wq006_strong_h20r10', 'run_8fedee28b1d84c1ebd4b'),
    ('switch_amount_lowvol_h10r5', 'run_c9871f3c547147bc80a1'),
    ('switch_amount_lowvol_h20r10', 'run_fe6c5b6b5f2d4a2395da'),
    ('switch_amount_lowvol_h10r5_quarter', 'run_9a68e61b294844ab9aa7'),
    ('switch_amount_lowvol_h20r10_quarter', 'run_7e94f022b5da43838f6f'),
]

def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')

def nav_stats(daily, capital):
    navs = [float(d['net_nav']) for d in daily]
    returns = [b/a-1 for a,b in zip(navs, navs[1:])]
    peak = navs[0]
    dd = 0.0
    for nav in navs:
        peak = max(peak, nav)
        dd = max(dd, 1-nav/peak)
    return {'net_return':navs[-1]/capital-1,
            'sharpe':statistics.mean(returns)/statistics.stdev(returns)*(252**0.5),
            'max_drawdown':dd, 'observations':len(daily)}

calendar = json.loads((DATA/'manifests/sha256'/GENERATION[:2]/(GENERATION+'.json')).read_text())['research_sessions']
code_sha = hashlib.sha256(Path(strategy.__file__).read_bytes()).hexdigest()
for key, run_id in CASES:
    if args.cases and key not in args.cases:
        continue
    raw = json.loads((BASE/'results'/f'{run_id}.json').read_text())
    spec = raw['run']['input']
    authored_state = key == 'wq006_strong_h20r10' or key.startswith('switch_amount_lowvol_')
    gate_label = ('authored_market_switch_breadth20' if key.startswith('switch_amount_lowvol_') else 'authored_loo_breadth20') if authored_state else args.market_gate
    if authored_state:
        assert args.market_gate == 'none', 'The selected formula already contains the LOO gate'
    if args.start or args.holdings or args.rebalance:
        assert args.market_gate!='none', 'Sensitivity overrides are limited to the cash-gate study'
        spec = {**spec,'start_date':args.start or spec['start_date'],
                'holdings_count':args.holdings or spec['holdings_count'],
                'rebalance_every_sessions':args.rebalance or spec['rebalance_every_sessions']}
    compiled = alpha_language.compile(spec['formula'])
    start = spec['start_date']
    i = next(i for i,s in enumerate(calendar) if s>=start)
    sessions = calendar[i-compiled.effective_lookback:calendar.index(END)+1]
    assert sessions[0]>='2025-08-01' and i>=compiled.effective_lookback
    started = time.monotonic()
    print(json.dumps({'phase':'read','key':key,'start':start,'end':END,'sessions_with_warmup':len(sessions)}),flush=True)
    bindings = {field:identifier for identifier,field in compiled.field_ids_by_identifier.items()}
    if args.market_gate!='none':
        bindings['price.close.adjusted']='close'
    data = MountedGenerationStore(DATA).read_columnar_slice(
        GENERATION,sessions=sessions,universe_name='top3000',
        neutralization=spec['neutralization'],
        field_bindings=bindings,
        fact_instrument_ids=frozenset())
    alpha = evaluate_columnar_alpha_matrix(data,compiled_alpha=compiled,
        neutralization=spec['neutralization'],cancellation_check=lambda:None)
    original_alpha_checksum = alpha['checksum']
    gate_series = []
    if args.market_gate=='breadth20':
        ids = tuple(sorted(data.instruments))
        indexes = {iid:i for i,iid in enumerate(ids)}
        closes = data.numeric_field_matrices(('price.close.adjusted',),ids)['price.close.adjusted']
        gate_by_session = {}
        for t,session in enumerate(data.sessions):
            member_indexes = [indexes[iid] for iid in data.universe_members[session]]
            history = closes[member_indexes,max(0,t-19):t+1]
            eligible = np.isfinite(history).all(axis=1) if t>=19 else np.zeros(len(member_indexes),dtype=bool)
            values = history[eligible]
            breadth = float(np.mean(values[:,-1]>values.mean(axis=1))) if len(values) else None
            risk_on = breadth is not None and breadth>=0.5
            gate_by_session[session] = risk_on
            gate_series.append({'signal_session':session,'eligible_stocks':int(np.count_nonzero(eligible)),
                                'above_ma20_fraction':breadth,'risk_on':risk_on})
        alpha = {**alpha,'sessions':[{**row,'values':row['values'] if gate_by_session[row['session']] else []} for row in alpha['sessions']]}
        alpha['checksum'] = alpha_matrix_checksum(alpha['sessions'])
    if args.board!='all':
        allowed_boards = {'main'} if args.board=='main' else {'main','chinext'}
        alpha = {**alpha,'sessions':[{**row,'values':[v for v in row['values']
                    if data.instruments[v['instrument_id']].board in allowed_boards]} for row in alpha['sessions']]}
        alpha['checksum'] = alpha_matrix_checksum(alpha['sessions'])
    original_transaction_cost = strategy.transaction_cost
    def cost_with_stress(raw_notional, side, costs):
        return strategy.money(original_transaction_cost(raw_notional,side,costs)
                              + raw_notional*Decimal(args.extra_cost_bps)/Decimal(10000))
    for capital in ((10000000,100000) if args.board=='all' and args.extra_cost_bps==0 and args.market_gate=='none' else (100000,)):
        ledger = []
        definition = {'strategy':{'holdings_count':spec['holdings_count'],
            'rebalance_interval':spec['rebalance_every_sessions'],'initial_cash_cny':str(capital)},'costs':COSTS}
        with patch.object(strategy,'INITIAL_CASH',Decimal(capital)), patch.object(strategy,'transaction_cost',cost_with_stress):
            result = strategy.run_strategy(data,alpha,definition,origin_session=start,ledger=ledger)
        independent = nav_stats(result['daily'],capital)
        assert abs(independent['sharpe']-result['metrics']['sharpe'])<1e-8
        assert abs(independent['max_drawdown']-result['metrics']['maximum_drawdown']['value'])<1e-8
        reference = {d['session']:d for d in json.loads((BASE/'observations'/f'{run_id}.json').read_text())['items']}
        # Source and terminal policies may differ. Exclude only the local terminal,
        # where the native longer run can still trade; preserve any mismatch.
        comparison = None
        if capital==10000000:
            rows = [dict(session=d['session'],local_nav=d['net_nav'],native_nav=reference[d['session']]['net_nav'],
                         absolute_difference=float(abs(Decimal(d['net_nav'])-Decimal(reference[d['session']]['net_nav']))))
                    for d in (result['daily'][:-1] if END<spec['end_date'] else result['daily'])]
            comparison = {'matched_sessions':len(rows),'maximum_absolute_nav_difference_cny':max(r['absolute_difference'] for r in rows),
                          'all_match_within_0_0001_cny':all(r['absolute_difference']<0.0001 for r in rows),
                          'excluded_local_terminal':END if END<spec['end_date'] else None,'rows':rows}
        evidence = {'experiment':'offline_capital_replay','key':key,'reference_run_id':run_id,
            'initial_cash_cny':capital,'source_generation':GENERATION,'data_through_session':END,
            'start':start,'end':END,'universe':'top3000','board_access':args.board,
            'account_filter':f'{args.board} board filter after original TOP3000 ranking and industry adjustment' if args.board!='all' else None,
            'extra_cost_bps_per_fill':args.extra_cost_bps,'original_alpha_checksum':original_alpha_checksum,
            'market_gate':gate_label,'market_gate_series':gate_series,
            'formula':spec['formula'],'neutralization':spec['neutralization'],
            'holdings_count':spec['holdings_count'],'rebalance_every_sessions':spec['rebalance_every_sessions'],
            'definition':definition,'strategy_source_sha256':code_sha,
            'result':result,'ledger':ledger,'independent_nav_stats':independent,'native_prefix_comparison':comparison}
        suffix = ('' if args.board=='all' else f'_{args.board}') + (f'_extra{args.extra_cost_bps}bp' if args.extra_cost_bps else '') + (f'_{args.market_gate}' if args.market_gate!='none' else '')
        if args.start or args.holdings or args.rebalance:
            suffix += f'_h{spec["holdings_count"]}r{spec["rebalance_every_sessions"]}_start{start}'
        save(OUTPUT/f'{key}_{capital}{suffix}.json',evidence)
        print(json.dumps({'phase':'result','key':key,'capital':capital,'board':args.board,'extra_cost_bps':args.extra_cost_bps,'market_gate':gate_label,**independent,
            'native_prefix_max_error':comparison['maximum_absolute_nav_difference_cny'] if comparison else None,
            'costs':result['metrics']['transaction_costs'],'elapsed_seconds':time.monotonic()-started}),flush=True)
    del data,alpha
    gc.collect()
