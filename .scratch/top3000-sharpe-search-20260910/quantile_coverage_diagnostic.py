"""Evidence for tied-score empty quantiles; no remote data export or product edits."""
import json
import math
from pathlib import Path
import numpy as np
from thesistrace.alpha_language import alpha_language
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.research_kernel.alpha import evaluate_columnar_alpha_matrix
from thesistrace.research_kernel.factor import factor_values, summarize_factor_days

ROOT=Path(__file__).resolve().parent
# Hand-constructed expectations: day1 q1=.01,q5=.03; day2 q1=-.05,q5 unavailable.
a=factor_values(list(range(40)),[.01]*8+[0.0]*24+[.03]*8)
b=factor_values([-2]*8+[-1]*2+[0]*30,[-.05]*8+[0.0]*32)
daily=[dict(session='toy1',**a),dict(session='toy2',**b)]
summary=summarize_factor_days(daily)
assert b['quantile_returns']['q5'] is None
assert all(x['quantile_reason'] is None for x in daily)
assert math.isclose(summary['quantile_returns']['q1'],-.02,abs_tol=1e-12)
assert math.isclose(summary['quantile_returns']['q5'],.03,abs_tol=1e-12)
assert math.isclose(summary['top_bottom_return'],.02,abs_tol=1e-12)
toy={'daily':daily,'summary':summary,'quantile_valid_session_count':2,
     'q1_valid_days':2,'q5_valid_days':1,'top_bottom_valid_days':1,
     'difference_of_separate_means':summary['quantile_returns']['q5']-summary['quantile_returns']['q1']}
print(json.dumps({'phase':'toy_checked','difference_of_means':toy['difference_of_separate_means'],
                  'mean_daily_spread':summary['top_bottom_return']}),flush=True)
plan=json.loads((ROOT/'round18-plan.json').read_text())
formula=next(f['formula'] for f in plan['factors'] if f['item_key']=='chl_spread20_low')
compiled=alpha_language.compile(formula)
sha='4723b071313705df8662131f4ec4137e4cf35a9680a7c63c1a0191eb66e83e7f'
source=ROOT/'offline-market'
calendar=json.loads((source/'manifests/sha256'/sha[:2]/(sha+'.json')).read_text())['research_sessions']
start,end='2025-09-10','2026-08-27'
sessions=calendar[calendar.index(start)-compiled.effective_lookback:calendar.index(end)+1]
assert sessions[0]>='2025-08-01'
data=MountedGenerationStore(source).read_columnar_slice(sha,sessions=sessions,universe_name='top3000',
     neutralization='none',field_bindings={field:identifier for identifier,field in compiled.field_ids_by_identifier.items()},fact_instrument_ids=frozenset())
print(json.dumps({'phase':'source_loaded','sessions':len(sessions)}),flush=True)
alpha=evaluate_columnar_alpha_matrix(data,compiled_alpha=compiled,neutralization='none',cancellation_check=lambda:None)
rows=[]
for day in alpha['sessions']:
    if day['session']<start:continue
    vals=[r['value'] for r in day['values']]
    # Independent average ordinal ranks, preserve whole ties.
    ordered=sorted(vals);n=len(ordered);groups={str(k):0 for k in range(1,6)}
    begin=0
    largest_tie=0
    while begin<n:
        stop=begin+1
        while stop<n and ordered[stop]==ordered[begin]:stop+=1
        average_zero_rank=(begin+stop-1)/2
        group=min(5,int(average_zero_rank*5/n)+1)
        groups[str(group)]+=stop-begin
        largest_tie=max(largest_tie,stop-begin)
        begin=stop
    rows.append({'session':day['session'],'valid_alpha_count':n,'q_counts_before_forward_label_filter':groups,
                 'largest_tie_count':largest_tie,'highest_score_tie_count':sum(v==ordered[-1] for v in vals) if vals else 0})
remote=json.loads((ROOT/'results/run_71964d3822e644108386.json').read_text())['factor']['factor']['horizons']
remote_comparison=[]
for h,v in remote.items():
    q=v['summary']['quantile_returns']
    remote_comparison.append({'horizon':int(h),'q1':q['q1'],'q5':q['q5'],
                             'difference_of_means':q['q5']-q['q1'],'reported_mean_daily_spread':v['summary']['top_bottom_return'],
                             'reported_quantile_valid_session_count':v['coverage']['quantile_valid_session_count']})
payload={'toy':toy,'source_generation':sha,'source_end':end,'formula':formula,'daily_alpha_counts':rows,
         'alpha_only_q5_empty_days':sum(r['q_counts_before_forward_label_filter']['5']==0 for r in rows),
         'alpha_only_q1_empty_days':sum(r['q_counts_before_forward_label_filter']['1']==0 for r in rows),
         'remote_summary':remote_comparison,
         'limits':'Local alpha counts are before future-label availability filtering and end8/27, so they are not remote q5 valid-day counts through9/9. Current code and toy prove different sample means can explain disparity. Do not claim exact remote daily attribution or arithmetic bug.'}
(ROOT/'quantile-coverage-diagnostic.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
lines=['# 并列评分、空分组与不同有效日期','',
       'CHL价差代理在截零后会产生大量相同评分。按平均名次分组不会强行拆开这些并列，某些日期可没有q5；q1、q5各自对有效日期取均值，多空差值只对两端同时存在的日期取均值。三个均值因此可能不是同一组日期。','',
       '手工40只股票两日例子：第一日q1=1%、q5=3%；第二日q1=-5%、q5为空。q5均值3%减q1均值-2%得到5%，但有效日的q5-q1均值只有2%。当前计算结果与该独立手算一致。两日均可计入整体quantile_valid_session_count，但q5有效日仅1日。','',
       '|预测期|远端q1均值|远端q5均值|两个均值相减|远端逐日多空差均值|整体分组有效日|',
       '|---:|---:|---:|---:|---:|---:|']
for r in remote_comparison:
    lines.append(f"|{r['horizon']}|{r['q1']:.4%}|{r['q5']:.4%}|{r['difference_of_means']:.4%}|{r['reported_mean_daily_spread']:.4%}|{r['reported_quantile_valid_session_count']}|")
lines+=['',f"本地同公式{len(rows)}个信号日中，未筛选未来标签前的q5为空有{payload['alpha_only_q5_empty_days']}日、q1为空有{payload['alpha_only_q1_empty_days']}日。这个局部证据止于2026-08-27，不能冒充远端9月9日结果的逐分组有效日期。",'',
        'MCP已返回整体分组、IC与Rank IC有效日，缺少各q1-q5及两端配对差值的有效日期数/日期集合。应让用户看到缺失的具体分组与样本期差异；本次记录诊断缺口，未认定计算错误。','',
        '代码证据：apps/core/src/thesistrace/research_kernel/factor.py（平均并列名次与逐列有效均值）、research_chunks.py（分组整体有效日及各项统计累积）；契约为research_run/result_schema.py的FactorCoverage。[完整证据](quantile-coverage-diagnostic.json)。','']
(ROOT/'QUANTILE_COVERAGE.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'sessions':len(rows),'q5_empty_alpha_days':payload['alpha_only_q5_empty_days'],'report':'QUANTILE_COVERAGE.md'}),flush=True)
