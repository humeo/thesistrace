"""Validate an authored leave-one-out breadth formula on existing local data."""
import gc
import json
from pathlib import Path
import numpy as np

from thesistrace.alpha_language import alpha_language
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.research_kernel.alpha import evaluate_columnar_alpha_matrix
from thesistrace.research_kernel.series_plan import _cross_section_ranks

BASE=Path(__file__).resolve().parent
plan=json.loads((BASE/'loo-breadth-plan.json').read_text())
formula=plan['formula']; binary=plan['binary_formula']
# Check the identity against the current rank implementation, including ties,
# all zero/all one, odd/even groups and exact 50% boundaries. n=1 is excluded.
toy_cases=0
for n in range(2,101):
    for ones in range(n+1):
        values=[(str(i),float(i<ones)) for i in range(n)]
        ranked=_cross_section_ranks(values)
        for iid,b in values:
            expected=(ones-b)/(n-1)
            actual=1+b-2*ranked[iid]
            assert abs(actual-expected)<1e-12,(n,ones,iid)
        toy_cases+=1

root=BASE/'offline-market'
sha='4723b071313705df8662131f4ec4137e4cf35a9680a7c63c1a0191eb66e83e7f'
manifest=json.loads((root/'manifests/sha256'/sha[:2]/(sha+'.json')).read_text())
calendar=manifest['research_sessions']; start='2025-09-10'; end='2026-08-27'
compiled=alpha_language.compile(formula)
sessions=calendar[calendar.index(start)-compiled.effective_lookback:calendar.index(end)+1]
data=MountedGenerationStore(root).read_columnar_slice(sha,sessions=sessions,
    universe_name='top3000',neutralization='none',
    field_bindings={field:identifier for identifier,field in compiled.field_ids_by_identifier.items()},
    fact_instrument_ids=frozenset())
def evaluate(source):
    return evaluate_columnar_alpha_matrix(data,compiled_alpha=alpha_language.compile(source),
                                         neutralization='none',cancellation_check=lambda:None)
binary_matrix=evaluate(binary)
population={}
for row in binary_matrix['sessions']:
    if row['session']<start:continue
    bs={v['instrument_id']:v['value'] for v in row['values']}
    assert all(b in (0,1) for b in bs.values())
    population[row['session']]=bs
del binary_matrix;gc.collect()

base=evaluate('-rank(ts_mean(amount,20))')
base_rows={r['session']:{v['instrument_id']:v['value'] for v in r['values']}
           for r in base['sessions'] if r['session']>=start}
del base;gc.collect()
native=evaluate(formula)
manual=json.loads((BASE/'capital-replay/lowamount_none_h10r10_100000_breadth20.json').read_text())
manual_gate={r['signal_session']:r for r in manual['market_gate_series']}
differences=[]; checks=[]
for row in native['sessions']:
    session=row['session']
    if session<start:continue
    bs=population[session]; n=len(bs); ones=sum(bs.values()); assert n>1
    expected={iid:value for iid,value in base_rows[session].items()
              if iid in bs and (ones-bs[iid])/(n-1)>=0.5}
    actual={v['instrument_id']:v['value'] for v in row['values']}
    assert expected==actual,(session,'native formula does not implement specified LOO gate')
    full_expected={iid:value for iid,value in base_rows[session].items() if iid in bs} if ones/n>=0.5 else {}
    old_expected=base_rows[session] if manual_gate[session]['risk_on'] else {}
    row_check={'session':session,'binary_population':n,'above_ma20':ones,'breadth':ones/n,
               'loo_eligible':len(actual),'full_gate_eligible':len(full_expected),
               'old_offline_eligible':len(old_expected),'equal_full_gate':actual==full_expected,
               'equal_old_offline_gate':actual==old_expected}
    checks.append(row_check)
    if actual!=old_expected: differences.append(row_check)

summary={'toy_rank_distributions':toy_cases,'native_formula_sessions_verified':len(checks),
         'start':start,'end':end,'source_generation':sha,
         'minimum_binary_population':min(r['binary_population'] for r in checks),
         'full_gate_different_sessions':sum(not r['equal_full_gate'] for r in checks),
         'old_offline_gate_different_sessions':len(differences),
         'differences':differences,'sessions':checks,
         'proof':'Authored formula exactly matches independent per-stock LOO count on every verified session. Whole-market gate is a separate comparator, not assumed identical.'}
(BASE/'loo-breadth-proof.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k not in ('sessions','differences')},ensure_ascii=False))
print(json.dumps({'differences':differences[:8]},ensure_ascii=False))
