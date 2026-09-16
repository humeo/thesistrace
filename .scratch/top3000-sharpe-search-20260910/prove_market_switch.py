"""Check authored score switching against raw-price breadth and integer counts."""
import gc
import json
from decimal import Decimal
from pathlib import Path
import numpy as np
from thesistrace.alpha_language import alpha_language
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.research_kernel.alpha import evaluate_columnar_alpha_matrix

BASE = Path(__file__).resolve().parent
plan = json.loads((BASE / 'round16-plan.json').read_text())
sha = '4723b071313705df8662131f4ec4137e4cf35a9680a7c63c1a0191eb66e83e7f'
root = BASE / 'offline-market'
start, end = '2025-09-10', '2026-08-27'
calendar = json.loads((root / 'manifests/sha256' / sha[:2] / (sha + '.json')).read_text())['research_sessions']
compiled = alpha_language.compile(plan['variants'][0]['formula'])
sessions = calendar[calendar.index(start) - compiled.effective_lookback:calendar.index(end) + 1]
data = MountedGenerationStore(root).read_columnar_slice(sha, sessions=sessions,
    universe_name='top3000', neutralization='none',
    field_bindings={field:identifier for identifier,field in compiled.field_ids_by_identifier.items()},
    fact_instrument_ids=frozenset())

def evaluate(source):
    rows = evaluate_columnar_alpha_matrix(data, compiled_alpha=alpha_language.compile(source),
        neutralization='none', cancellation_check=lambda:None)
    return {r['session']:{v['instrument_id']:v['value'] for v in r['values']}
            for r in rows['sessions'] if r['session'] >= start}

ids = tuple(sorted(data.instruments))
index = {iid:i for i,iid in enumerate(ids)}
closes = data.numeric_field_matrices(('price.close.adjusted',), ids)['price.close.adjusted']
population = {}
for t, session in enumerate(data.sessions):
    if session < start:
        continue
    members = sorted(data.universe_members[session])
    history = closes[[index[iid] for iid in members], t-19:t+1]
    valid = np.isfinite(history).all(axis=1)
    population[session] = {iid:int(row[-1] > row.mean()) for iid,row,ok in zip(members,history,valid) if ok}
native_binary = evaluate(plan['binary_formula'])
binary_differences = []
for session, expected in population.items():
    actual = native_binary[session]
    for iid in expected.keys() | actual.keys():
        if expected.get(iid) != actual.get(iid):
            t = list(data.sessions).index(session)
            history = closes[index[iid], t-19:t+1]
            binary_differences.append({'session':session,'instrument_id':iid,
                'raw_binary':expected.get(iid),'native_binary':actual.get(iid),
                'close':float(history[-1]),'numpy_mean':float(history.mean()),
                'window_min':float(history.min()),'window_max':float(history.max()),
                'close_minus_numpy_mean':float(history[-1]-history.mean()),
                'close_window':history.tolist()})
if binary_differences:
    (BASE / 'market-switch-binary-differences.json').write_text(json.dumps(binary_differences,indent=2)+'\n')
    print(json.dumps({'binary_difference_count':len(binary_differences),'examples':binary_differences[:6]}),flush=True)
# The upstream binary may differ at a binary64 tie. Preserve that evidence,
# then require the actual decision and selected scores to match independent
# raw-price population counts exactly; never silently force the binary equal.
assert all(abs(Decimal(str(r['close'])) - sum(Decimal(str(x)) for x in r['close_window']) / 20) == 0
           for r in binary_differences), 'Non-tie binary discrepancy needs investigation'
del native_binary
amount = evaluate(plan['amount_formula'])
lowvol = evaluate(plan['lowvol_formula'])
state = evaluate(plan['state_formula'])
rows = []
for session, bs in population.items():
    n, total = len(bs), sum(bs.values())
    assert n > 1
    expected = {iid:int(2*(total-b) >= n-1) for iid,b in bs.items()}
    assert state[session] == expected, (session, 'State differs from independent integer counts')
    common = bs.keys() & amount[session].keys() & lowvol[session].keys()
    rows.append({'session':session, 'population':n, 'above_ma':total,
                 'common_valid':len(common), 'amount_valid':len(amount[session]),
                 'lowvol_valid':len(lowvol[session]),
                 'strong_common':sum(expected[iid] for iid in common),
                 'weak_common':sum(1-expected[iid] for iid in common),
                 'mixed_state_in_population':len(set(expected.values())) > 1})
del state
gc.collect()
score_checks = 0
maximum_error = 0.0
for variant in plan['variants']:
    actual = evaluate(variant['formula'])
    for session, bs in population.items():
        n, total = len(bs), sum(bs.values())
        common = bs.keys() & amount[session].keys() & lowvol[session].keys()
        expected = {}
        for iid in common:
            strong = 2*(total-bs[iid]) >= n-1
            if variant['name'] == 'market_switch_amount_lowvol':
                expected[iid] = amount[session][iid] if strong else lowvol[session][iid]
            elif strong:
                expected[iid] = amount[session][iid]
        assert actual[session].keys() == expected.keys(), (variant['name'], session, 'Eligibility differs')
        error = max((abs(actual[session][iid] - value) for iid,value in expected.items()), default=0.0)
        assert error < 1e-12, (variant['name'], session, error)
        maximum_error = max(maximum_error, error)
        score_checks += len(expected)
    del actual
    gc.collect()
summary = {'source_generation':sha, 'start':start, 'end':end,
           'session_count':len(rows), 'variant_session_checks':len(rows)*len(plan['variants']),
           'score_checks':score_checks, 'maximum_score_error':maximum_error,
           'raw_price_binary_equal_native':not binary_differences,
           'upstream_binary_discrepancies':len(binary_differences),
           'discrepancies_are_decimal_string_ties':True,
           'raw_binary_method':'numpy mean of binary64 adjusted close; alternative to canonical compensated sum',
           'state_equals_independent_integer_counts':True,
           'switch_and_cash_match_common_validity':True,
           'mixed_state_days':[r['session'] for r in rows if r['mixed_state_in_population']],
           'amount_eligibility_removed_by_common_validity':sum(r['amount_valid']-r['common_valid'] for r in rows),
           'rows':rows}
(BASE / 'market-switch-proof.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k != 'rows'}), flush=True)
