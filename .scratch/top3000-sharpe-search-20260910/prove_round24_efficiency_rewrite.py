"""Validate algebraic recovery without changing the252-session hypothesis."""
import hashlib
import json
import math
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from thesistrace.alpha_language import alpha_language
from thesistrace.research_kernel.capacity import plan_session_capacity
from thesistrace.research_kernel.series_plan import (
    build_series_execution_plan, evaluate_columnar_execution_matrix, evaluate_series_execution_matrix)

ROOT = Path(__file__).resolve().parent
original = 'rank(revenue / assets - lag(revenue / assets, 252) + 0 * log(assets) + 0 * log(lag(assets, 252)))'
rewritten = 'rank(delta(revenue / assets + 0 * log(assets), 252))'
formulas = [original, rewritten]
compiled = [alpha_language.compile(s) for s in formulas]
plans = [build_series_execution_plan(c) for c in compiled]
assert all(c.effective_lookback == 252 for c in compiled)
assert compiled[0].field_ids_by_identifier == compiled[1].field_ids_by_identifier
ids = tuple(f'synthetic:{i:03}' for i in range(64))
sessions = tuple((date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(494))
rng = np.random.default_rng(20260910)
# Repeated visible values and step changes, not fabricated real company financials.
assets = np.repeat(rng.lognormal(20, 1, (64, 9)), 60, axis=1)[:, :494]
revenue = assets * np.repeat(rng.uniform(-.3, 2, (64, 9)), 60, axis=1)[:, :494]
assets[0, :] = 1; revenue[0, :] = 0
assets[1, :] = 2; revenue[1, :] = 0
assets[2, 10:22] = 0
assets[3, 265:273] = -3
assets[4, 2:13] = np.nan
revenue[5, 252:270] = np.nan
assets[6, 23] = np.inf
revenue[7, 280] = np.inf
assets[8, 0] = 1e-300; revenue[8, 0] = 1e300
assets[9, 300] = 1e-300; revenue[9, 300] = 1e300
assets[10, :] = .25
revenue[11, :] = -0.0
fields = {compiled[0].field_ids_by_identifier['assets']: assets,
          compiled[0].field_ids_by_identifier['revenue']: revenue}
members = {s: tuple(iid for i, iid in enumerate(ids) if (i + j // 37) % 13 != 0) for j, s in enumerate(sessions)}

def rank_values(values):
    ordered = sorted(values, key=lambda iid: values[iid]); result = {}; a = 0; n = len(ordered)
    while a < n:
        b = a + 1
        while b < n and values[ordered[b]] == values[ordered[a]]: b += 1
        rank = .5 if n == 1 else (a + b - 1) / (2 * (n - 1))
        for iid in ordered[a:b]: result[iid] = rank
        a = b
    return result

expected = np.full((len(ids), len(sessions)), np.nan)
for j in range(252, len(sessions)):
    valid = {}
    for i, iid in enumerate(ids):
        if iid not in members[sessions[j]]: continue
        a, a0, v, v0 = [float(x) for x in (assets[i, j], assets[i, j-252], revenue[i, j], revenue[i, j-252])]
        if not all(math.isfinite(x) for x in (a, a0, v, v0)) or a <= 0 or a0 <= 0: continue
        x, x0 = v/a, v0/a0
        value = x-x0
        if all(math.isfinite(z) for z in (x, x0, value)): valid[iid] = value
    for iid, value in rank_values(valid).items(): expected[ids.index(iid), j] = value

comparisons = []; matrices = []
for label, c, p in zip(('original', 'rewritten'), compiled, plans):
    matrix = evaluate_columnar_execution_matrix(p, ids, sessions, fields, members, cancellation_check=lambda: None)
    row = evaluate_series_execution_matrix(p, ids,
        lambda iid: {k: [float(v) if math.isfinite(v) else None for v in m[ids.index(iid)]] for k, m in fields.items()},
        length=len(sessions), sessions=sessions, universe_members=members)
    row_matrix = np.array([[np.nan if v is None else v for v in row[iid]] for iid in ids])
    assert np.array_equal(matrix, expected, equal_nan=True)
    assert np.array_equal(row_matrix, expected, equal_nan=True)
    # Real kernel on independent bounded windows with the same252day context.
    parts = []
    for start in range(252, len(sessions), 64):
        stop = min(start+64, len(sessions)); begin = start-252
        window = sessions[begin:stop]
        part = evaluate_columnar_execution_matrix(p, ids, window, {k: v[:, begin:stop] for k, v in fields.items()},
            {s: members[s] for s in window}, cancellation_check=lambda: None)
        parts.append(part[:, 252:])
    assert np.array_equal(np.concatenate(parts, axis=1), expected[:, 252:], equal_nan=True)
    matrices.append(matrix)
    capacity = plan_session_capacity(formula_work=c.estimated_work,node_count=c.node_count,field_count=2,
        maximum_universe_cardinality=3000,effective_lookback=c.effective_lookback,execution_memory_bytes=1536*1024**2)
    comparisons.append({'label':label,'formula':c.source,'node_count':c.node_count,'estimated_work':c.estimated_work,
        'effective_lookback':c.effective_lookback,'row_columnar_independent_exact':True,'bounded_window_comparison_exact':True,
        'capacity_model_example_3000members_1536MiB':asdict(capacity)})
assert np.array_equal(matrices[0],matrices[1],equal_nan=True)
payload = {'source':'Deterministic synthetic inputs, no private data transfer','research_sessions':242,'warmup_sessions':252,
    'instruments':len(ids),'possible_research_scores':64*242,'valid_research_scores':int(np.isfinite(expected).sum()),
    'edge_cases':['positive/zero/negative/missing/nonfiniteassets','negative/zero/missing/nonfiniterevenue','divisionoverflow','repeatedratios/ties','changingcurrentuniverse','gapsbetweenendpoints','64sessionchunkswith252sessioncontext'],
    'comparisons':comparisons,'algebra':'For currentandlagged finitepositiveassets, each0*log term iszero. Moving assetpositivitygate inside delta preserves bothendpointvalidity and difference. Invaliddivision/intermediateoverflow remainsmissing.',
    'limitation':'Synthetic row/columnar/windowed alpha equivalence, not fullWorkercheckpoint/PIT generation proof. Capacitymodel is illustrative, not measuredremoteRSS. Must compare the recovered realfactor summary exactly with source before economic conclusions or secondH20attempt.'}
(ROOT/'round24-rewrite-proof.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(payload),flush=True)
