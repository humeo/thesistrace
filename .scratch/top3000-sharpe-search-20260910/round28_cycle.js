
const root = "/Users/koltenluca/code-github/thesistrace/.scratch/top3000-sharpe-search-20260910";
const unwrap = r => r.structuredContent || JSON.parse(r.content.find(c => c.type === "text").text);
async function save(path, obj) {
    return await tools.apply_patch("*** Begin Patch\n*** Add File: "+root+"/"+path+"\n+"+
        JSON.stringify(obj,null,2).split("\n").join("\n+")+"\n*** End Patch");
}
async function snapshot() {
    const r = await tools.exec_command({cmd:"UV_CACHE_DIR=/private/tmp/thesistrace-qs-uv-cache uv run --project apps/core --no-sync --offline python - <<'PY'\nimport json,hashlib\nfrom pathlib import Path\nD=Path('.scratch/top3000-sharpe-search-20260910');p=D/'round28-plan.json';plan=json.loads(p.read_text());subs=[json.loads(p.read_text()) for p in sorted((D/'submissions').glob('r28-*.json'))];batches={p.stem:json.loads(p.read_text()) for p in (D/'batches').glob('*.json')};runs={p.stem:json.loads(p.read_text()) for p in (D/'runs').glob('*.json')};results={p.stem for p in (D/'results').glob('*.json')}\nactive=[];ready=[];fail=[];unknown=[]\nfor s in subs:\n r=s['response']\n if r.get('outcome')!='accepted':continue\n if 'batch_id' in r:\n  x=batches.get(r['batch_id']);items=x['items'] if x else []\n  if not x or x['status'] in {'queued','running','cancelling'}:active.append({'kind':'batch','id':r['batch_id']})\n else:\n  x=runs.get(r['run_id']);items=[{'research_run_id':r['run_id'],'status':x['status'] if x else None}]\n  if not x or x['status'] in {'queued','running','cancelling'}:active.append({'kind':'run','id':r['run_id']})\n for i in items:\n  rid=i['research_run_id']\n  if i['status']=='succeeded' and rid not in results:ready.append(rid)\n  if i['status']=='failed' and rid not in runs:fail.append(rid)\nprint(json.dumps({'plan_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'active':active,'ready':ready,'failed_missing_detail':fail,'existing_result_ids':sorted(results),'submissions':[{'key':s['key'],'definition_key':s['definition_key'],'input':{'start_date':s['input']['start_date'],'holdings_count':s['input'].get('holdings_count')},'response':{'outcome':s['response'].get('outcome'),'run_id':s['response'].get('run_id')},'run_status':runs.get(s['response'].get('run_id'),{}).get('status')} for s in subs],'definitions':[{**{k:e[k] for k in ('key','formula','neutralization','hypothesis','source_name','execution_route')},'cases':[c for c in plan['cases'] if c['definition_key']==e['key'] and c['status_at_freeze']=='planned']} for e in plan['definitions'] if any(c['definition_key']==e['key'] and c['status_at_freeze']=='planned' for c in plan['cases'])]},ensure_ascii=False))\nPY",max_output_tokens:40000});
    if (r.exit_code!==0) throw Error(r.output);
    return JSON.parse(r.output);
}
const initial=await snapshot(), complete=new Set(initial.ready), failed=new Set(initial.failed_missing_detail);
const polls=await Promise.allSettled(initial.active.map(x=>x.kind==="batch"?
    tools.mcp__quanttrace__get_research_batch({batch_id:x.id}):tools.mcp__quanttrace__get_research_run({run_id:x.id})));
for(let j=0;j<polls.length;j++) {
    const x=initial.active[j], p=polls[j];
    if(p.status!=="fulfilled")throw Error(x.id+": "+String(p.reason));
    const state=unwrap(p.value);
    if(!state.id)throw Error(JSON.stringify(state));
    await save((x.kind==="batch"?"batches":"runs")+"/"+state.id+".json",state);
    text({id:state.id,status:state.status,progress:state.progress});
    const items=x.kind==="batch"?state.items:[{research_run_id:state.id,status:state.status}];
    for(const i of items) {
        if(i.status==="succeeded"&&!initial.existing_result_ids.includes(i.research_run_id)) complete.add(i.research_run_id);
        if(i.status==="failed") failed.add(i.research_run_id);
    }
}
const completedOutputs=[];
for(const id of complete) {
    const queries=await Promise.allSettled([
        tools.mcp__quanttrace__get_research_run({run_id:id}),
        ...["factor","provenance","strategy_summary"].map(section=>tools.mcp__quanttrace__get_research_run_result({run_id:id,section}))
    ]);
    if(queries.some(q=>q.status!=="fulfilled"))throw Error("Incomplete collection "+id);
    const [run,factor,provenance,summary]=queries.map(q=>unwrap(q.value));
    if(run.status!=="succeeded"||!factor.factor||!provenance.authoring_input||!summary.metrics)throw Error("Malformed result "+id);
    await save("runs/"+id+".json",run);
    await save("results/"+id+".json",{run,factor,provenance,summary});
    completedOutputs.push({id,name:run.name,sharpe:summary.metrics.sharpe,net:summary.metrics.net_cumulative_return,
        dd:summary.metrics.maximum_drawdown.value});
}
for(const id of failed) {
    const run=unwrap(await tools.mcp__quanttrace__get_research_run({run_id:id}));
    if(!run.id)throw Error("Missing failure state "+id);
    await save("runs/"+id+".json",run);
    text({failed_run:id,failure_reason:run.failure_reason});
}
text({collected:completedOutputs});
const validation=await tools.exec_command({cmd:"UV_CACHE_DIR=/private/tmp/thesistrace-qs-uv-cache uv run --project apps/core --no-sync --offline python .scratch/top3000-sharpe-search-20260910/render_round28.py",max_output_tokens:1800});
if(validation.exit_code!==0)throw Error(validation.output);
text(validation.output);
const current=await snapshot();
const resolutionRead=await tools.exec_command({cmd:"UV_CACHE_DIR=/private/tmp/thesistrace-qs-uv-cache uv run --project apps/core --no-sync --offline python .scratch/top3000-sharpe-search-20260910/verify_round28_admissions.py",max_output_tokens:3000});
if(resolutionRead.exit_code!==0)throw Error(resolutionRead.output);
const resolutions=JSON.parse(resolutionRead.output);
const rejected=current.submissions.filter(s=>s.response.outcome!=="accepted"&&!resolutions[s.key]);
if(rejected.length) {
    text({manual_admission_review_needed:rejected.map(s=>s.key)}); return;
}
const maxActive=load("round28MaxInFlight") ?? 4;
let available=Math.max(0,maxActive-current.active.length);
const attempted=new Set(current.submissions.filter(s=>s.input.start_date==="2025-09-10").map(s=>s.definition_key));
for(const d of current.definitions) {
    if(available<=0)break;
    const prior=current.submissions.filter(s=>s.definition_key===d.key && s.input.start_date==="2025-09-10" && s.response.outcome==="accepted");
    const resolution=Object.values(resolutions).find(r=>r.definition_key===d.key);
    if(resolution?.decision==="terminal_admission_unresolved")continue;
    if(d.execution_route==="single"||resolution?.decision==="one_exact_single_per_holdings") {
        if(prior.some(s=>["failed","cancelled"].includes(s.run_status))) {
            text({definition_unresolved:d.key,reason:"Prior single execution failed; no unchanged retry or remaining N dispatch"});
            continue;
        }
        const doneHoldings=new Set(prior.map(s=>s.input.holdings_count));
        const next=d.cases.find(c=>!doneHoldings.has(c.holdings_count));
        if(!next)continue;
        if(prior.some(s=>s.run_status!=="succeeded"))continue;
        const key="r28-"+d.key+"-year-h"+next.holdings_count;
        const label=d.source_name.replace(/^QS\d+(\s+(1y|3y))?\s+/,"").replace(/\s+H\d+\s+R\d+\b/g,"").slice(0,44);
        const input={request_id:"qs28-audit-"+d.key+"-year-h"+next.holdings_count+"-20260910-v1",
            folder_id:"folder_batch_research",name:"QS28 1y "+d.key+" "+label+" H"+next.holdings_count+" R20",
            formula:d.formula,hypothesis:d.hypothesis,research_kind:"strategy_backtest",
            holdings_count:next.holdings_count,rebalance_every_sessions:20,
            start_date:"2025-09-10",end_date:"2026-09-09",universe:"top3000",neutralization:d.neutralization};
        const response=unwrap(await tools.mcp__quanttrace__submit_research_run(input));
        await save("submissions/"+key+".json",{key,submitted_at:new Date().toISOString(),input,response,
            source_plan:"round28-plan.json",source_plan_sha256:current.plan_sha256,definition_key:d.key,
            execution_route_reason:resolution ? "Reviewed batch capacity admission rejection; exact singles once; H20 only after H10 succeeds" : "Frozen252financial single route; H20 only after H10 succeeds",
            admission_resolution:resolution ? "round28-admission-resolutions.json" : null});
        text({submitted:key,name:d.source_name,response});available--;
        if(response.outcome!=="accepted")break;
        continue;
    }
    if(attempted.has(d.key))continue;
    const key="r28-"+d.key+"-year",input={batch_kind:"strategy_sweep",request_id:"qs28-audit-"+d.key+"-year-20260910-v1",
        alpha:{formula:d.formula,hypothesis:d.hypothesis},
        strategies:d.cases.map(c=>({item_key:"h"+c.holdings_count+"r20",
            name:"QS28 1y "+d.key+" "+d.source_name.replace(/^QS\d+(\s+(1y|3y))?\s+/,"").replace(/\s+H\d+\s+R\d+\b/g,"").slice(0,44)+" H"+c.holdings_count+" R20",
            holdings_count:c.holdings_count,rebalance_every_sessions:20})),
        start_date:"2025-09-10",end_date:"2026-09-09",universe:"top3000",neutralization:d.neutralization};
    const response=unwrap(await tools.mcp__quanttrace__submit_research_batch(input));
    await save("submissions/"+key+".json",{key,submitted_at:new Date().toISOString(),input,response,
        source_plan:"round28-plan.json",source_plan_sha256:current.plan_sha256,definition_key:d.key});
    text({submitted:key,name:d.source_name,response}); available--;
    if(response.outcome!=="accepted")break;
}
