"""Independent Decimal cash/fees/NAV checks; does not import the strategy kernel."""
import csv
import json
from collections import Counter
from decimal import Decimal, localcontext
from pathlib import Path
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

BASE = Path(__file__).resolve().parent
rows = []
for folder in ('capital-replay','capital-replay-latest'):
    if not (BASE/folder).exists():
        continue
    paths = sorted((BASE/folder).glob('*.json'))
    cases = [(p,json.loads(p.read_text())) for p in paths]
    coordinates = set()
    for _,case in cases:
        for day in case['ledger']:
            coordinates.update(day['session']+'|'+f['instrument_id'] for f in day['fills'])
            coordinates.update(day['session']+'|'+p['instrument_id'] for p in day['positions'])
    root = BASE/('latest-market' if folder.endswith('latest') else 'offline-market')
    def manifest(sha):
        return json.loads((root/'manifests/sha256'/sha[:2]/(sha+'.json')).read_text())
    generation = manifest(cases[0][1]['source_generation'])
    identity_family = manifest(next(f['manifest_sha256'] for f in generation['families'] if f['family_id']=='market.instrument_identity'))
    identity_table = manifest(identity_family['tables'][0]['manifest_sha256'])
    board_by_id = {}
    for obj in identity_table['objects']:
        sha = obj['sha256']
        table = pq.read_table(root/'objects/sha256'/sha[:2]/(sha+'.parquet'),columns=['instrument_id','board'])
        board_by_id.update((r['instrument_id'],r['board']) for r in table.to_pylist())
    price_family = manifest(next(f['manifest_sha256'] for f in generation['families'] if f['family_id']=='equity.eod_price'))
    price_table = manifest(price_family['tables'][0]['manifest_sha256'])
    requested = pa.array(sorted(coordinates),type=pa.string())
    prices = {}
    for obj in price_table['objects']:
        sha = obj['sha256']; path = root/'objects/sha256'/sha[:2]/(sha+'.parquet')
        if not path.exists():
            continue
        table = pq.read_table(path,columns=['session_date','instrument_id','open_raw','open_adj'])
        keys = pc.binary_join_element_wise(pc.cast(table['session_date'],pa.string()),table['instrument_id'],'|')
        table = table.filter(pc.is_in(keys,value_set=requested))
        for row in table.to_pylist():
            prices[(str(row['session_date']),row['instrument_id'])]=(row['open_raw'],row['open_adj'])
    for p,d in cases:
        if d.get('experiment')!='offline_capital_replay':
            continue
        board_key = {'all_platform_boards_unconfirmed_for_user':'all','all':'all','main':'main','main_chinext':'main_chinext'}[d['board_access']]
        allowed_boards = {'all':{'main','chinext','star'},'main':{'main'},'main_chinext':{'main','chinext'}}[board_key]
        fees = cash_error = nav_error = fee_error = Decimal(0)
        cash = Decimal(d['initial_cash_cny'])
        positions = {}
        raw_cash = cash
        settlement_bridge = Decimal(0)
        counts = Counter()
        session_indexes = {s:i for i,s in enumerate(generation['research_sessions'])}
        gate = {r['signal_session']:r['risk_on'] for r in d.get('market_gate_series',[])}
        notionals = []
        with localcontext() as ctx:
            ctx.prec = 80
            for day in d['ledger']:
                if day['cycle_type']=='terminal_valuation':
                    assert not day['fills']
                signal = day['signal']
                if signal is not None:
                    assert all(board_by_id[iid] in allowed_boards for iid in signal['selected_instrument_ids']), (p, day['session'], 'Ineligible target board')
                    signal_session = signal['session']
                    assert session_indexes[day['session']]-session_indexes[signal_session]==1
                    assert (session_indexes[signal_session]-session_indexes[d['start']])%d['rebalance_every_sessions']==0
                    if gate:
                        if not gate[signal_session]:
                            counts['cash_target_decisions'] += 1
                            assert signal['selected_instrument_ids']==[]
                            assert all(f['side']=='sell' for f in day['fills'])
                        else:
                            counts['stock_target_decisions'] += 1
                            assert len(signal['selected_instrument_ids'])<=d['holdings_count']
                day_fees = Decimal(0)
                for fill in day['fills']:
                    counts['fills'] += 1
                    iid = fill['instrument_id']; quantity = fill['quantity']
                    assert board_by_id[iid] in allowed_boards, (p, day['session'], 'Ineligible fill board')
                    raw_price,adjusted_price = prices[(day['session'],iid)]
                    assert raw_price==Decimal(fill['raw_open'])
                    notional = Decimal(fill['raw_open'])*fill['quantity']
                    assert notional==Decimal(fill['raw_notional'])
                    commission = max(notional*Decimal('0.0003'),Decimal(5))
                    counts['minimum_commission_fills'] += commission==Decimal(5)
                    expected = commission + notional*Decimal('0.00001')
                    if fill['side']=='sell':
                        expected += notional*Decimal('0.0005')
                    expected += notional*Decimal(d.get('extra_cost_bps_per_fill',0))/10000
                    actual = Decimal(fill['cost'])
                    fee_error = max(fee_error,abs(expected-actual))
                    day_fees += actual
                    if fill['side']=='buy':
                        old_shares,old_units = positions.get(iid,(0,Decimal(0)))
                        positions[iid]=(old_shares+quantity,old_units+Decimal(quantity)*raw_price/adjusted_price)
                        cash -= notional+actual
                    else:
                        old_shares,old_units = positions[iid]
                        assert 0<quantity<=old_shares
                        removed = old_units*Decimal(quantity)/Decimal(old_shares)
                        settlement = removed*adjusted_price
                        settlement_bridge += settlement-notional
                        cash += settlement-actual
                        if quantity==old_shares:
                            del positions[iid]
                        else:
                            positions[iid]=(old_shares-quantity,old_units-removed)
                    raw_cash += -notional-actual if fill['side']=='buy' else notional-actual
                    notionals.append(float(notional))
                    assert cash>=-Decimal('0.000001'),(p,day['session'],'negative cash')
                fees += day_fees
                assert abs(day_fees-Decimal(day['transaction_cost_cny']))<Decimal('0.000001')
                assert abs(fees-Decimal(day['cumulative_transaction_cost']))<Decimal('0.000001')
                cash_error = max(cash_error,abs(cash-Decimal(day['net_cash'])))
                assert abs((cash-raw_cash)-settlement_bridge)<Decimal('0.000001')
                actual_positions = {r['instrument_id']:r for r in day['positions']}
                assert all(board_by_id[iid] in allowed_boards for iid in actual_positions), (p, day['session'], 'Ineligible held board')
                assert set(positions)==set(actual_positions)
                for iid,(shares,units) in positions.items():
                    assert shares==actual_positions[iid]['execution_shares']
                    assert abs(units-Decimal(actual_positions[iid]['adjusted_units']))<Decimal('0.000001')
                    price = prices.get((day['session'],iid))
                    if price is not None:
                        assert price[1]==Decimal(actual_positions[iid]['last_adjusted_price'])
                nav = cash + sum(Decimal(pos['adjusted_units'])*Decimal(pos['last_adjusted_price']) for pos in day['positions'])
                nav_error = max(nav_error,abs(nav-Decimal(day['net_nav'])))
                assert all(pos['execution_shares']>0 and Decimal(pos['adjusted_units'])>0 for pos in day['positions'])
        assert max(cash_error,nav_error,fee_error)<Decimal('0.000001'),(p,cash_error,nav_error,fee_error)
        m=d['result']['metrics']
        rows.append({'file':str(p.relative_to(BASE)),'key':d['key'],'capital':d['initial_cash_cny'],
            'start':d['start'],'end':d['end'],'board':board_key,
            'market_gate':d.get('market_gate','none'),
            'holdings':d['holdings_count'],'rebalance':d['rebalance_every_sessions'],
            'extra_cost_bps':d.get('extra_cost_bps_per_fill',0),
            'net_profit_cny':float(Decimal(d['result']['daily'][-1]['net_nav'])-Decimal(d['initial_cash_cny'])),
            **d['independent_nav_stats'], 'fees_cny':float(fees),
            'mean_cash_ratio':m['cash_ratio']['mean'],'mean_holdings':m['holdings_count']['mean'],
            'maximum_single_weight':m['maximum_single_name_weight']['period_maximum']['value'],
            'fills':counts['fills'],'minimum_commission_fills':counts['minimum_commission_fills'],
            'cash_target_decisions':counts['cash_target_decisions'],'stock_target_decisions':counts['stock_target_decisions'],
            'synthetic_settlement_adjustment_cny':float(settlement_bridge),
            'accounting_model':'synthetic total return, not broker cash settlement',
            'board_access_verified':True,
            'max_cash_error':str(cash_error),'max_nav_error':str(nav_error),'max_fee_error':str(fee_error),
            'native_nav_match':d['native_prefix_comparison']['all_match_within_0_0001_cny'] if d['native_prefix_comparison'] else None})
if rows:
    with (BASE/'capital-replay-audit.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (BASE/'capital-replay-audit.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps({'runs':len(rows),'independent_cash_nav_fees_verified':True,
                 'latest_100k_runs':sum(r['capital']==100000 and r['end']=='2026-09-09' for r in rows)}))
