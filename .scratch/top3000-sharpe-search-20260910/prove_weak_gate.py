"""Verify weak and strong breadth gates with independent integer population counts."""
import gc
import json
from pathlib import Path
from thesistrace.alpha_language import alpha_language
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.research_kernel.alpha import evaluate_columnar_alpha_matrix

BASE=Path(__file__).resolve().parent
weak=json.loads((BASE/'round12-plan.json').read_text())['formula']
binary=json.loads((BASE/'loo-breadth-plan.json').read_text())['binary_formula']
strong=f'-rank(ts_std(pct_change(close, 1), 20)) + 0 * log((1 + {binary} - 2 * rank({binary})) - 0.5 + 0.000000000001)'
root=BASE/'offline-market'
sha='4723b071313705df8662131f4ec4137e4cf35a9680a7c63c1a0191eb66e83e7f'
manifest=json.loads((root/'manifests/sha256'/sha[:2]/(sha+'.json')).read_text())
calendar=manifest['research_sessions']; start='2025-09-10'; end='2026-08-27'
compiled=alpha_language.compile(weak)
sessions=calendar[calendar.index(start)-compiled.effective_lookback:calendar.index(end)+1]
data=MountedGenerationStore(root).read_columnar_slice(sha,sessions=sessions,
    universe_name='top3000',neutralization='none',
    field_bindings={field:identifier for identifier,field in compiled.field_ids_by_identifier.items()},
    fact_instrument_ids=frozenset())
def evaluate(source):
    rows=evaluate_columnar_alpha_matrix(data,compiled_alpha=alpha_language.compile(source),
        neutralization='none',cancellation_check=lambda:None)
    return {r['session']:{v['instrument_id']:v['value'] for v in r['values']}
            for r in rows['sessions'] if r['session']>=start}
population=evaluate(binary)
base=evaluate('-rank(ts_std(pct_change(close, 1), 20))')
rows=[]
for label,formula in [('weak',weak),('strong',strong)]:
    actual=evaluate(formula)
    for session,bs in population.items():
        n=len(bs); total=sum(bs.values()); assert n>1
        assert all(v in (0,1) for v in bs.values())
        eligible={iid:value for iid,value in base[session].items() if iid in bs}
        expected={iid:value for iid,value in eligible.items()
                  if ((2*(total-bs[iid]) < n-1) if label=='weak' else (2*(total-bs[iid]) >= n-1))}
        assert actual[session]==expected,(label,session)
        rows.append({'gate':label,'session':session,'population':n,'eligible_base':len(eligible),'expected_count':len(expected),'actual_count':len(actual[session])})
    del actual;gc.collect()
for session in population:
    day=[r for r in rows if r['session']==session]
    assert len(day)==2 and sum(r['actual_count'] for r in day)==day[0]['eligible_base']
summary={'source_generation':sha,'start':start,'end':end,'population_sessions':len(population),
         'gate_session_checks':len(rows),'minimum_population':min(len(x) for x in population.values()),
         'native_values_equal_independent_integer_count_gate':True,'weak_and_strong_partition_valid_base':True,
         'weak_formula':weak,'strong_formula':strong,'rows':rows}
(BASE/'weak-breadth-proof.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k not in {'rows','weak_formula','strong_formula'}}))
