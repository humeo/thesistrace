"""Verify fixed conditional continuity against directly counted daily signs."""
import json
from pathlib import Path

import numpy as np

from thesistrace.alpha_language import alpha_language
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.research_kernel.alpha import evaluate_columnar_alpha_matrix

ROOT = Path(__file__).resolve().parent
plan = json.loads((ROOT / 'round23-plan.json').read_text())
sha = '4723b071313705df8662131f4ec4137e4cf35a9680a7c63c1a0191eb66e83e7f'
source = ROOT / 'offline-market'
calendar = json.loads((source / 'manifests/sha256' / sha[:2] / (sha + '.json')).read_text())['research_sessions']
end = '2026-08-27'
last = calendar.index(end)
sessions = calendar[last - 120:last + 1]
assert len(sessions) == 121 and sessions[0] >= '2025-08-01'
compiled = [alpha_language.compile(f['formula']) for f in plan['factors']]
assert all(c.effective_lookback == 120 for c in compiled)
data = MountedGenerationStore(source).read_columnar_slice(
    sha, sessions=sessions, universe_name='top3000', neutralization='none',
    field_bindings={'price.close.adjusted': 'close'}, fact_instrument_ids=frozenset())
ids = tuple(sorted(data.instruments))
index = {iid: i for i, iid in enumerate(ids)}
closes = data.numeric_field_matrices(('price.close.adjusted',), ids)['price.close.adjusted']
members = sorted(data.universe_members[end])
momentum, continuity = {}, {}
for iid in members:
    # The last20 intervals are intentionally absent from both formation inputs.
    p = closes[index[iid]][:101]
    if np.isfinite(p).all() and (p > 0).all():
        changes = p[1:] / p[:-1] - 1
        momentum[iid] = float(p[-1] / p[0] - 1)
        continuity[iid] = (int((changes > 0).sum()) - int((changes < 0).sum())) / 100

def average_rank(values):
    ordered = sorted(values, key=lambda iid: values[iid])
    result = {}
    begin, n = 0, len(ordered)
    while begin < n:
        stop = begin + 1
        while stop < n and values[ordered[stop]] == values[ordered[begin]]:
            stop += 1
        value = .5 if n == 1 else (begin + stop - 1) / (2 * (n - 1))
        for iid in ordered[begin:stop]:
            result[iid] = value
        begin = stop
    return result

rank_m = average_rank(momentum)
pool = {iid for iid, value in rank_m.items() if value > .8 and momentum[iid] > 0}
expected = {
    'fip_winner_continuity': average_rank({iid: continuity[iid] for iid in pool}),
    'winner_momentum_control': average_rank({iid: momentum[iid] for iid in pool}),
    'continuity_formation_control': average_rank(continuity),
}
native, comparisons = {}, []
for f, c in zip(plan['factors'], compiled):
    key = f['item_key']
    actual = evaluate_columnar_alpha_matrix(data, compiled_alpha=c, neutralization='none', cancellation_check=lambda: None)
    final = next(x for x in actual['sessions'] if x['session'] == end)
    observed = {v['instrument_id']: v['value'] for v in final['values']}
    native[key] = observed
    unmatched = sorted(expected[key].keys() ^ observed.keys())
    errors = {iid: abs(expected[key][iid] - observed[iid]) for iid in expected[key].keys() & observed.keys()}
    differing = [{'instrument_id': iid, 'independent': expected[key][iid], 'kernel': observed[iid]} for iid in sorted(errors) if errors[iid] > 1e-10]
    comparison = {'key': key, 'effective_lookback': c.effective_lookback, 'expected_valid': len(expected[key]),
                  'native_valid': len(observed), 'unmatched_ids': unmatched,
                  'max_rank_error': max(errors.values(), default=0), 'differing_score_count': len(differing), 'examples': differing[:12]}
    comparisons.append(comparison)
    print(json.dumps(comparison), flush=True)
matched = native['fip_winner_continuity'].keys() == native['winner_momentum_control'].keys()
top_overlap = {}
for n in (10, 20):
    sets = [set(sorted(native[key], key=lambda iid: (-native[key][iid], iid))[:n])
            for key in ('fip_winner_continuity', 'winner_momentum_control')]
    top_overlap[str(n)] = len(sets[0] & sets[1])
payload = {'source_generation': sha, 'source_end': end, 'evaluated_session': end,
           'warmup_first_session': sessions[0], 'formation_end_session': sessions[100],
           'price_observations_loaded': len(sessions), 'price_observations_used_per_formation': 101,
           'daily_signs_counted': 100, 'eligible_common_count': len(momentum), 'winner_pool_count': len(pool),
           'comparisons': comparisons, 'winner_coverage_matched': matched, 'same_signal_day_top_name_overlap': top_overlap,
           'limits': 'Single fully-warmed8/27signal from already-local rawdata. Directcount/average-rank proof only; not latestperformance, fullremoteIC audit, economicindependence or broker holdings. Top overlap assumes deterministicinstrumenttie order for this signal diagnostic only.'}
(ROOT / 'round23-signal-proof.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
assert matched and not any(x['unmatched_ids'] or x['differing_score_count'] for x in comparisons), 'Persisted differences require diagnosis'
print(json.dumps({'status': 'verified', 'winner_coverage_matched': matched, 'top_overlap': top_overlap}), flush=True)
