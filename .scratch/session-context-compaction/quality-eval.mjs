// Fixed synthetic-source retention probe. Does not qualify a whole Agent workflow.
import { createRequire } from 'node:module';
import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { parseEnv } from 'node:util';
import { extractionInstruction, semanticVerdicts } from './quality-semantics.mjs';
const root = fileURLToPath(new URL('../../', import.meta.url)).replace(/\/$/, '');
const require = createRequire(`${root}/agent/package.json`);
const load = async name => import(pathToFileURL(require.resolve(name)).href);
const { Mastra } = await load('@mastra/core/mastra');
const { noopLogger } = await load('@mastra/core/logger');
const { RequestContext } = await load('@mastra/core/request-context');
const { InMemoryStore } = await load('@mastra/core/storage');
const { createOpenAI } = await load('@ai-sdk/openai');
const local = name => import(pathToFileURL(`${root}/agent/dist/${name}.js`).href);
const { readModelRegistry } = await local('model-registry');
const { RegisteredModelRuntime } = await local('model-runtime');
const { GuardedLanguageModel, RunModelObservation } = await local('guarded-language-model');
const { RunUsageCapture, normalizeTokenUsage } = await local('usage-capture');
const { generateSessionContext } = await local('session-context-generation');
const { estimateModelInput } = await local('model-context');
const message = (id, role, text, offset) => ({id,role,createdAt:new Date(Date.UTC(2026,8,7,0,0,offset)),threadId:'eval-session',resourceId:'eval-owner',content:{format:2,parts:[{type:'text',text}]}});
const tool = (id,args,result,offset) => ({...message(id,'assistant','',offset),content:{format:2,parts:[{type:'tool-invocation',toolInvocation:{state:'result',toolCallId:`call_${id}`,toolName:'get_research_run_result',args,result}}]}});
const first = [message('goal','user','Compare the momentum run with the quality run. Use point-in-time data. Maintain 20 holdings and rebalance every 5 trading sessions; neither parameter may change. Report negative IC honestly; do not reverse the alpha automatically.',0),tool('result-a',{run_id:'run_eval_momentum',section:'factor'},{run_id:'run_eval_momentum',status:'succeeded',dataset_generation:'generation_eval_20260907',rank_ic:-0.072,coverage:'1341/1362',request_id:'request_eval_first',next_cursor:'cursor_eval_page_002',query:{section:'factor',horizon:20}},1),message('pending','assistant','Momentum result is read. Quality run is still pending. Next read the momentum cursor with unchanged section=factor and horizon=20, then inspect quality. Do not submit another run.',2)];
const increment = [tool('result-b',{run_id:'run_eval_quality',section:'factor'},{run_id:'run_eval_quality',status:'succeeded',rank_ic:0.041,request_id:'request_eval_quality',next_cursor:null},3),message('updated','user','Both results are available. Finish the comparison without submitting new research. Keep point-in-time data and the original holdings/rebalance constraints.',4)];
const long = [message('past','user','Use the immutable result for generation_eval_long. No recalculation or automatic retry of already successful submissions.',0),message('long-goal','user','Read all result pages for run_eval_long and explain the blocked continuation without fabricating missing data.',1),tool('prefix',{run_id:'run_eval_long',section:'strategy'},{run_id:'run_eval_long',status:'succeeded',request_id:'request_eval_long',rows:Array.from({length:800},(_,i)=>({session:`session_${String(i).padStart(4,'0')}`,nav:1+i/10000})),next_cursor:'cursor_eval_long_801'},2),message('prefix-error','assistant','The subsequent read returned CURSOR_VERSION_MISMATCH for cursor_eval_long_801. Preserve the successful run and request identity. Stop continuation; inspect the current result version before choosing a valid cursor. Do not claim all pages have been read.',3)];
const cases=[{id:'first',removed:first,required:['run_eval_momentum','request_eval_first','cursor_eval_page_002'],facts:['generation_eval_20260907','-0.072','1341/1362'],prefix:[]},{id:'incremental',removed:increment,required:['run_eval_quality','request_eval_quality','run_eval_momentum'],facts:['0.041','-0.072'],prefix:[],incremental:true},{id:'long-turn',removed:long,required:['run_eval_long','request_eval_long','cursor_eval_long_801','CURSOR_VERSION_MISMATCH'],facts:['generation_eval_long'],prefix:['prefix','prefix-error']}];
if(process.argv.includes('--preflight')) { console.log(JSON.stringify({cases:cases.map(c=>({id:c.id,sourceMessages:c.removed.length,sourceBytes:Buffer.byteLength(JSON.stringify(c.removed)),requiredReferences:c.required.length})),liveCalls:0})); process.exit(0); }
const privateEnv=parseEnv(readFileSync(process.env.THESISTRACE_CONTEXT_EVAL_ENV_FILE,'utf8'));
const registry=readModelRegistry(readFileSync(`${root}/config/model-registry.json`,'utf8'),privateEnv);
const selected=registry.models.find(m=>m.key===registry.defaultModelKey);
if(!selected || selected.providerAdapter!=='openai') throw Error('EVAL_CONFIG_INVALID');
const baseURL=privateEnv.THESISTRACE_AGENT_OPENAI_BASE_URL;
if(!baseURL || !['127.0.0.1','localhost','host.docker.internal'].includes(new URL(baseURL).hostname)) throw Error('EVAL_ENDPOINT_INVALID');
const hostURL=new URL(baseURL); if(hostURL.hostname==='host.docker.internal') hostURL.hostname='127.0.0.1';
const spendLimit=Number(process.env.THESISTRACE_CONTEXT_EVAL_SPEND_LIMIT_USD);
if(!Number.isFinite(spendLimit)||spendLimit<=0||spendLimit>5) throw Error('EVAL_SPEND_INVALID');
const referencePricing={input:0.50,output:1.80,cachedInput:0.04,basis:'repository published-standard-upper-bound snapshot 2026-08-31; not proxy invoice'};
const provider=createOpenAI({apiKey:selected.credential,baseURL:hostURL.href})(selected.providerModelId);
const template=new RegisteredModelRuntime(registry).resolve(selected.key,selected.defaultReasoningEffort);
let actualCost=0,unknownUsage=false; const callReports=[],caseReports=[]; let previous;
for(const testCase of cases){
 const started=performance.now(); const firstCall=callReports.length; let candidate; let semantics={extracted:false}; let errorCode=null;
 const capture=new RunUsageCapture();
 const observed={specificationVersion:'v3',provider:provider.provider,modelId:provider.modelId,supportedUrls:provider.supportedUrls,doGenerate:async()=>{throw Error('EVAL_STREAM_REQUIRED')},doStream:async request=>{
  const reserve=(selected.contextWindow*referencePricing.input+request.maxOutputTokens*referencePricing.output)/1e6;
  if(unknownUsage||actualCost+reserve>spendLimit||callReports.length>=12) throw Error('EVAL_SPEND_STOP');
  const report={caseId:testCase.id,inputEstimate:estimateModelInput(request),maxOutputTokens:request.maxOutputTokens,usage:null,costUsd:null,durationMs:null};callReports.push(report);
  const start=performance.now(); let output;
  try { output=await provider.doStream(request); } catch(error) { unknownUsage=true; throw error; }
  return {...output,stream:output.stream.pipeThrough(new TransformStream({transform(part,controller){if(part.type==='finish'){
   const usage=normalizeTokenUsage(part.usage);report.usage=usage;report.durationMs=Math.round(performance.now()-start);
   const input=usage.inputTokens.total,output=usage.outputTokens.total,cached=usage.inputTokens.cacheRead??0;
   if(input===null||output===null||cached>input) unknownUsage=true;
   else {report.costUsd=((input-cached)*referencePricing.input+cached*referencePricing.cachedInput+output*referencePricing.output)/1e6;actualCost+=report.costUsd;}
  }controller.enqueue(part);},flush(){if(report.usage===null)unknownUsage=true;}}))};
 }};
 const guarded=new GuardedLanguageModel(observed,new RunModelObservation(capture),selected,'memory');
 try{
  if(testCase.incremental&&!previous) throw Error('EVAL_PRIOR_FAILED');
  candidate=await generateSessionContext({removed:testCase.removed,turnPrefixMessageIds:testCase.prefix,requiredReferences:testCase.required,previous:testCase.incremental?previous:undefined,selection:{...template,memoryLanguageModel:guarded},storage:new InMemoryStore(),mastra:new Mastra({logger:noopLogger}),requestContext:new RequestContext(),abortSignal:AbortSignal.timeout(600000)});
  // Extract state from the actual candidate, never from source messages or oracle answers.
  const result=await guarded.doStream({prompt:[{role:'system',content:extractionInstruction},{role:'user',content:[{type:'text',text:JSON.stringify({memory:candidate.memory,summary:candidate.summary})}]}],maxOutputTokens:8192,providerOptions:template.providerOptions,abortSignal:AbortSignal.timeout(120000)});
  let answer='',completed=false;
  for await (const part of result.stream) {
   if(part.type==='error')throw Error('EVAL_EXTRACTION_FAILED');
   if(part.type==='text-delta')answer+=part.delta;
   if(part.type==='finish')completed=part.finishReason.unified==='stop';
  }
  if(!completed)throw Error('EVAL_EXTRACTION_INCOMPLETE');
  semantics=semanticVerdicts(testCase.id,JSON.parse(answer));
 }catch {errorCode='CONTEXT_EVAL_CASE_FAILED';}
 const assertions={generated:!!candidate,references:!!candidate&&testCase.required.every(v=>candidate.summary.includes(v)),facts:!!candidate&&testCase.facts.every(v=>(candidate.memory+'\n'+candidate.summary).includes(v)),accounting:callReports.slice(firstCall).length>0&&callReports.slice(firstCall).every(c=>c.costUsd!==null)};
 caseReports.push({id:testCase.id,sourceBytes:Buffer.byteLength(JSON.stringify(testCase.removed)),assertions,semantics,succeeded:Object.values(assertions).every(Boolean)&&Object.values(semantics).every(Boolean),durationMs:Math.round(performance.now()-started),errorCode});
 if(testCase.id==='first'&&candidate)previous=candidate;
 if(unknownUsage)break;
}
const report={modelKey:selected.key,effort:selected.defaultReasoningEffort,contextWindow:selected.contextWindow,maxOutputTokens:selected.maxOutputTokens,referencePricing,spendLimitUsd:spendLimit,costUsd:actualCost,unknownUsage,cases:caseReports,calls:callReports,complete:caseReports.length===cases.length&&caseReports.every(c=>c.succeeded),scope:'Synthetic candidate retention and independent state extraction with case oracles; no executed continuation, whole-agent qualification or real financial data'};
writeFileSync(process.env.THESISTRACE_CONTEXT_EVAL_REPORT,JSON.stringify(report,null,2)+'\n',{mode:0o600});
console.log(JSON.stringify({complete:report.complete,cases:caseReports.map(c=>({id:c.id,succeeded:c.succeeded})),costUsd:actualCost,calls:callReports.length}));
if(!report.complete)process.exitCode=1;
