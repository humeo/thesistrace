"""Audit fixed-contract factor repeats and aggregate sample comparability."""
import json, math
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parent
groups=defaultdict(list)
for path in sorted((ROOT/'results').glob('*.json')):
    r=json.loads(path.read_text())
    if 'factor' not in r:continue
    i=r['run']['input'];p=r['provenance']
    key=(i['formula'],i['start_date'],i['end_date'],i['universe'],i['neutralization'],
         p['data']['generation_id'],json.dumps(p['execution']['semantic_versions'],sort_keys=True),
         p['execution']['calculation_contracts']['numeric_execution_contract'])
    groups[key].append(r)
def differences(a,b,path=''):
    out=[]
    if isinstance(a,dict) and isinstance(b,dict):
        for k in sorted(a.keys()|b.keys()):
            if k not in a or k not in b:out.append({'path':path+'.'+k,'left':a.get(k),'right':b.get(k),'kind':'missing_key'})
            else:out.extend(differences(a[k],b[k],path+'.'+k))
    elif isinstance(a,(int,float)) and isinstance(b,(int,float)):
        if a!=b:out.append({'path':path,'left':a,'right':b,'absolute_error':abs(a-b),'kind':'numeric'})
    elif a!=b:out.append({'path':path,'left':a,'right':b,'kind':'value'})
    return out
repeats=[];quantiles=[]
for key,rs in groups.items():
    baseline=rs[0]
    for r in rs[1:]:
        diffs=differences(baseline['factor']['factor'],r['factor']['factor'])
        repeats.append({'left_run':baseline['run']['id'],'right_run':r['run']['id'],'exact_equal':not diffs,'differences':diffs})
    for h,item in baseline['factor']['factor']['horizons'].items():
        s=item['summary'];q=s['quantile_returns'];tb=s['top_bottom_return']
        diff=None if q['q1'] is None or q['q5'] is None else q['q5']-q['q1']
        discrepancy=None if diff is None or tb is None else diff-tb
        if discrepancy is not None and abs(discrepancy)>1e-10:
            quantiles.append({'run_id':baseline['run']['id'],'name':baseline['run']['name'],'start':key[1],'end':key[2],'horizon':int(h),
                'q1':q['q1'],'q5':q['q5'],'difference_of_means':diff,'mean_paired_spread':tb,'discrepancy':discrepancy,
                'opposite_signs':diff*tb<0,'overall_quantile_valid_days':item['coverage']['quantile_valid_session_count']})
material=[x for x in repeats if any(d['kind']!='numeric' or d['absolute_error']>1e-12 for d in x['differences'])]
out={'created_at':datetime.now(timezone.utc).isoformat(),'factor_records':sum(map(len,groups.values())),'unique_frozen_cases':len(groups),
     'same_case_repeat_comparisons':len(repeats),'exact_equal_repeats':sum(x['exact_equal'] for x in repeats),
     'material_repeat_differences':material,'repeat_checks':repeats,
     'different_sample_mean_rows':sorted(quantiles,key=lambda r:abs(r['discrepancy']),reverse=True),
     'opposite_sign_rows':sum(r['opposite_signs'] for r in quantiles),
     'scope':'Same formula, period, neutralization, universe, generation and declared numeric/semantic contracts. Comparisons include factor-only and strategy-associated factors. Quantile mismatch identifies an aggregate comparability gap; it is not an arithmetic-error test and does not recover absent group-day counts.'}
(ROOT/'factor-comparability-audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
lines=['# 因子重复结果与分组样本口径核对','',
       f"已核对{out['factor_records']}份因子摘要，按公式、区间、Universe、中性化、Data Generation和数值/语义版本归并为{out['unique_frozen_cases']}个冻结案例。相同案例共有{len(repeats)}次重复比较，{out['exact_equal_repeats']}次完全一致，超过1e-12的数值差异或结构差异有{len(material)}次。",'',
       '这是已有真实结果的可重复性核对，不是新增因子试验，也不代表从原始行情独立重算每个IC。包含单独因子评估与不同持仓/调仓参数的策略关联因子。','',
       f"三个预测期合计有{len(quantiles)}行出现q5均值减q1均值与每日配对差值均值相差超过1e-10，其中{out['opposite_sign_rows']}行方向相反。平均所用日期可以不同；当前摘要不能恢复每组及配对的有效日期数。",'',
       '|冻结案例代表|起点|预测期|q5-q1两个均值之差|逐日配对差均值|差距|符号相反|',
       '|---|---|---:|---:|---:|---:|---|']
for r in out['different_sample_mean_rows']:
    lines.append(f"|[{r['name']}](https://thesistrace.com/research-runs/{r['run_id']})|{r['start']}|{r['horizon']}|{r['difference_of_means']:.4%}|{r['mean_paired_spread']:.4%}|{r['discrepancy']:.4%}|{'是' if r['opposite_signs'] else '否'}|")
lines+=['','有差距的行需要同时读分组覆盖与配对差值，不应将两种口径混写成同一个“多空收益”。完整重复比较和所有异常汇总保存在[机器证据](factor-comparability-audit.json)。[并列评分与空分组复现](QUANTILE_COVERAGE.md)解释了一种已确认的产生机制，不能由摘要反推所有行的逐日原因。','']
(ROOT/'FACTOR_COMPARABILITY.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({k:out[k] for k in ['factor_records','unique_frozen_cases','same_case_repeat_comparisons','exact_equal_repeats','material_repeat_differences','opposite_sign_rows']},ensure_ascii=False))
print(json.dumps({'different_sample_mean_rows':len(quantiles),'largest':out['different_sample_mean_rows'][:8]},ensure_ascii=False))
