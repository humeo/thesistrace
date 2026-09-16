"""Check raw-moment DSL against independently centered daily returns."""
import json
import math
from pathlib import Path

import numpy as np

from thesistrace.alpha_language import alpha_language
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.research_kernel.alpha import evaluate_columnar_alpha_matrix

ROOT = Path(__file__).resolve().parent
plan = json.loads((ROOT/'round25-plan.json').read_text())
sha = '4723b071313705df8662131f4ec4137e4cf35a9680a7c63c1a0191eb66e83e7f'
source = ROOT/'offline-market'
calendar = json.loads((source/'manifests/sha256'/sha[:2]/(sha+'.json')).read_text())['research_sessions']
dates = ['2025-09-10','2025-12-31','2026-03-31','2026-06-30','2026-08-27']
compiled = [alpha_language.compile(f['formula']) for f in plan['factors']]
assert all(c.effective_lookback == 20 for c in compiled)
store = MountedGenerationStore(source)

def ranks(values):
    ordered = sorted(values, key=lambda iid: values[iid]); result = {}; a = 0; n = len(ordered)
    while a<n:
        b=a+1
        while b<n and values[ordered[b]]==values[ordered[a]]: b+=1
        value=.5 if n==1 else (a+b-1)/(2*(n-1))
        for iid in ordered[a:b]: result[iid]=-value
        a=b
    return result

comparisons=[]; numerical=[]; top_overlap=[]
for end in dates:
    last=calendar.index(end); sessions=calendar[last-20:last+1]
    assert len(sessions)==21 and sessions[0]>='2025-08-01'
    data=store.read_columnar_slice(sha,sessions=sessions,universe_name='top3000',neutralization='none',
        field_bindings={'price.close.adjusted':'close'},fact_instrument_ids=frozenset())
    ids=tuple(sorted(data.instruments)); indices={iid:i for i,iid in enumerate(ids)}
    prices=data.numeric_field_matrices(('price.close.adjusted',),ids)['price.close.adjusted']
    expected_raw={f['item_key']:{} for f in plan['factors']}
    raw_error=[]; sigmas=[]; g1s=[]
    for iid in sorted(data.universe_members[end]):
        p=prices[indices[iid]]
        if not np.isfinite(p).all() or not (p>0).all(): continue
        r=p[1:]/p[:-1]-1; centered=r-float(np.mean(r)); sigma=float(np.sqrt(np.mean(centered*centered)))
        if sigma==0: continue
        g1=float(np.mean(centered*centered*centered)/(sigma*sigma*sigma))
        mu=float(np.mean(r)); expanded=float((np.mean(r*r*r)-3*mu*np.mean(r*r)+2*mu*mu*mu)/(sigma*sigma*sigma))
        raw_error.append(abs(g1-expanded)); sigmas.append(sigma); g1s.append(g1)
        expected_raw['total_daily_skew20_low'][iid]=g1
        expected_raw['lowmax20_skew_coverage'][iid]=float(np.max(r))
        expected_raw['lowvol20_skew_coverage'][iid]=sigma
    native={}
    for f,c in zip(plan['factors'],compiled):
        key=f['item_key']; alpha=evaluate_columnar_alpha_matrix(data,compiled_alpha=c,neutralization='none',cancellation_check=lambda:None)
        values=next(s['values'] for s in alpha['sessions'] if s['session']==end)
        actual={v['instrument_id']:v['value'] for v in values}; native[key]=actual
        expected=ranks(expected_raw[key]); unmatched=sorted(expected.keys()^actual.keys())
        errors={iid:abs(expected[iid]-actual[iid]) for iid in expected.keys()&actual.keys()}
        differences=[{'id':iid,'expected':expected[iid],'kernel':actual[iid]} for iid in sorted(errors) if errors[iid]>1e-10]
        comparisons.append({'session':end,'key':key,'expected_valid':len(expected),'native_valid':len(actual),
            'unmatched':unmatched,'max_rank_error':max(errors.values(),default=0),'differing_scores':len(differences),'examples':differences[:10]})
    assert all(native[key].keys()==native['total_daily_skew20_low'].keys() for key in native)
    numerical.append({'session':end,'max_raw_centered_g1_error':max(raw_error),'min_positive_sigma':min(sigmas),'max_abs_g1':max(map(abs,g1s)),
                      'fisher_pearson_abs_bound':18/math.sqrt(19)})
    for n in (10,20):
        candidate=set(sorted(native['total_daily_skew20_low'],key=lambda iid:(-native['total_daily_skew20_low'][iid],iid))[:n])
        for key in ('lowmax20_skew_coverage','lowvol20_skew_coverage'):
            control=set(sorted(native[key],key=lambda iid:(-native[key][iid],iid))[:n])
            top_overlap.append({'session':end,'n':n,'control':key,'common_names':len(candidate&control)})
    print(json.dumps({'session':end,'comparisons':comparisons[-3:],'numerical':numerical[-1]}),flush=True)
payload={'source_generation':sha,'source_end':'2026-08-27','evaluated_sessions':dates,'comparison_count':len(comparisons),
    'comparisons':comparisons,'numerical':numerical,'same_session_top_name_overlap':top_overlap,
    'compiled':[{'key':f['item_key'],'node_count':c.node_count,'work':c.estimated_work,'lookback':c.effective_lookback} for f,c in zip(plan['factors'],compiled)],
    'limitations':'Fivepredetermined fullywarmed localdates, notremoteperformance orallremotealpha outputaudit. Centeredmoments computedindependently; noepsilon floor,clippingorwinsorization. Rankingdifferences andnearzerovariance issues mustbekept iffound. Overlap is signalname diagnostic, notexecutedportfolioorindependentfamily evidence.'}
(ROOT/'round25-signal-proof.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
assert not any(c['unmatched'] or c['differing_scores'] for c in comparisons), 'Persisted differences need diagnosis before submission'
assert max(x['max_raw_centered_g1_error'] for x in numerical)<1e-9
assert all(x['max_abs_g1']<=x['fisher_pearson_abs_bound']+1e-10 for x in numerical)
print(json.dumps({'status':'verified','valid_scores':sum(c['native_valid'] for c in comparisons)}),flush=True)
