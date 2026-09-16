"""Check new authored signals against independent regression and rolling windows."""
import json
import math
from pathlib import Path

import numpy as np

from thesistrace.alpha_language import alpha_language
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.research_kernel.alpha import evaluate_columnar_alpha_matrix

ROOT = Path(__file__).resolve().parent
plan = json.loads((ROOT / 'round20-plan.json').read_text())
sha = '4723b071313705df8662131f4ec4137e4cf35a9680a7c63c1a0191eb66e83e7f'
source = ROOT / 'offline-market'
calendar = json.loads((source / 'manifests/sha256' / sha[:2] / (sha + '.json')).read_text())['research_sessions']
end = '2026-08-27'
last = calendar.index(end)
sessions = calendar[last - 79:last + 1]
assert sessions[0] >= '2025-08-01' and len(sessions) == 80
compiled = [alpha_language.compile(f['formula']) for f in plan['factors']]
assert [x.effective_lookback for x in compiled] == [61, 61, 79, 79]
data = MountedGenerationStore(source).read_columnar_slice(
    sha, sessions=sessions, universe_name='top3000', neutralization='none',
    field_bindings={'price.close.adjusted': 'close'}, fact_instrument_ids=frozenset())
ids = tuple(sorted(data.instruments))
index = {iid: i for i, iid in enumerate(ids)}
closes = data.numeric_field_matrices(('price.close.adjusted',), ids)['price.close.adjusted']
members = sorted(data.universe_members[end])
expected_raw = {f['item_key']: {} for f in plan['factors']}
regression_errors = []

def ar_increment(returns):
    x, y = returns[:-1], returns[1:]
    if np.std(x) == 0:
        return None
    # QR/SVD least squares with an intercept; does not reuse kernel moments.
    intercept, beta = np.linalg.lstsq(np.column_stack((np.ones(len(x)), x)), y, rcond=None)[0]
    forecast_increment = intercept + beta * returns[-1] - y.mean()
    moment_beta = ((x * y).mean() - x.mean() * y.mean()) / np.var(x)
    moment_increment = moment_beta * (returns[-1] - x.mean())
    regression_errors.append(abs(float(forecast_increment - moment_increment)))
    return float(forecast_increment)

def historical_instability(returns):
    vols = np.array([np.std(returns[i:i + 20]) for i in range(60)])
    if vols.mean() == 0:
        return None, None
    return float(np.std(vols) / vols.mean()), float(vols[-1])

for iid in members:
    p = closes[index[iid]]
    short = p[-62:]
    if np.isfinite(short).all() and (short > 0).all():
        returns = short[1:] / short[:-1] - 1
        score = ar_increment(returns)
        if score is not None:
            expected_raw['ar1_increment60'][iid] = score
            expected_raw['reversal1_ar_coverage'][iid] = float(returns[-1])
    if np.isfinite(p).all() and (p > 0).all():
        returns = p[1:] / p[:-1] - 1
        cv, level = historical_instability(returns)
        if cv is not None:
            expected_raw['historical_vol_instability20_60_low'][iid] = cv
            expected_raw['lowvol20_instability_coverage'][iid] = level

def ordinal_rank(values, sign):
    ordered = sorted(values, key=lambda iid: values[iid])
    result = {}
    begin, n = 0, len(ordered)
    while begin < n:
        stop = begin + 1
        while stop < n and values[ordered[stop]] == values[ordered[begin]]:
            stop += 1
        rank = .5 if n == 1 else (begin + stop - 1) / (2 * (n - 1))
        for iid in ordered[begin:stop]:
            result[iid] = sign * rank
        begin = stop
    return result

comparisons = []
native = {}
for f, c in zip(plan['factors'], compiled):
    actual = evaluate_columnar_alpha_matrix(data, compiled_alpha=c, neutralization='none', cancellation_check=lambda: None)
    final = next(x for x in actual['sessions'] if x['session'] == end)
    native[f['item_key']] = {v['instrument_id']: v['value'] for v in final['values']}
    expected = ordinal_rank(expected_raw[f['item_key']], 1 if f['item_key'] == 'ar1_increment60' else -1)
    observed = native[f['item_key']]
    unmatched = sorted(expected.keys() ^ observed.keys())
    errors = {iid: abs(expected[iid] - observed[iid]) for iid in expected.keys() & observed.keys()}
    different = [{'instrument_id': iid, 'independent': expected[iid], 'kernel': observed[iid]} for iid in sorted(errors) if errors[iid] > 1e-10]
    comparison = {'key': f['item_key'], 'effective_lookback': c.effective_lookback,
                  'expected_valid': len(expected), 'native_valid': len(observed),
                  'unmatched_ids': unmatched, 'max_rank_error': max(errors.values(), default=0),
                  'differing_score_count': len(different), 'examples': different[:12]}
    comparisons.append(comparison)
    print(json.dumps(comparison), flush=True)

rng = np.random.default_rng(20260910)
r = rng.normal(.0004, .012, 61)
permuted = r.copy()
permuted[1:-1] = rng.permutation(r[1:-1])
a, b = ar_increment(r), ar_increment(permuted)
assert math.isclose(float(np.prod(1 + r)), float(np.prod(1 + permuted)), abs_tol=1e-12)
assert math.isclose(float(np.std(r)), float(np.std(permuted)), abs_tol=1e-12)
assert np.max(r) == np.max(permuted) and sum(r > 0) == sum(permuted > 0) and r[-1] == permuted[-1]
assert abs(a - b) > 1e-8
v = rng.normal(0, np.linspace(.005, .025, 79))
cv1, level1 = historical_instability(v)
cv2, level2 = historical_instability(2 * v)
assert math.isclose(cv1, cv2, abs_tol=1e-12) and math.isclose(2 * level1, level2, abs_tol=1e-12)
coverage_matched = {name: native[a].keys() == native[b].keys() for name, a, b in [
    ('ar1_vs_reversal', 'ar1_increment60', 'reversal1_ar_coverage'),
    ('instability_vs_lowvol', 'historical_vol_instability20_60_low', 'lowvol20_instability_coverage')]}
payload = {'source_generation': sha, 'source_end': end, 'evaluated_session': end,
           'warmup_first_session': sessions[0], 'close_observations': len(sessions),
           'comparisons': comparisons, 'coverage_matched': coverage_matched,
           'max_ols_moment_increment_error': max(regression_errors),
           'order_toy': {'original': a, 'permuted': b, 'same_compound_return_vol_max_positive_count_last_return': True},
           'scale_toy': {'cv_original': cv1, 'cv_scaled_returns': cv2, 'vol_original': level1, 'vol_scaled_returns': level2},
           'limits': 'One-session formula semantics on already-local raw data and deterministic toys. Not remote/latest performance, not an IC audit, not proof of independent economic returns. Rank ties and eligibility differences are retained if found.'}
(ROOT / 'round20-signal-proof.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
assert not any(x['unmatched_ids'] or x['differing_score_count'] for x in comparisons), 'Saved formula differences require diagnosis'
assert all(coverage_matched.values()) and max(regression_errors) < 1e-10
print(json.dumps({'status': 'verified', 'coverage_matched': coverage_matched, 'evaluated_session': end}), flush=True)
