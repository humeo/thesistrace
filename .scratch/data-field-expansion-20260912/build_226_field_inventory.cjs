const fs=require('node:fs');
const path=require('node:path');
const base='.scratch/data-field-expansion-20260912';
const prior=JSON.parse(fs.readFileSync(base+'/dsl-field-inventory-223.json','utf8'));
const core=JSON.parse(fs.readFileSync(base+'/core-flow-ttm-3.json','utf8')).fields;
const evidence=JSON.parse(fs.readFileSync(base+'/production-mounted-evidence.json','utf8'));
const fields=[...prior.fields,...core];
const seen=new Set(['abs','log','sign','rank','lag','delta','pct_change','ts_mean','ts_sum','ts_std','ts_min','ts_max']);
for(const f of fields){
  if(!/^[a-z][a-z0-9_]*$/.test(f.dsl_identifier)||seen.has(f.dsl_identifier))throw Error('Bad identifier: '+f.dsl_identifier);
  seen.add(f.dsl_identifier);
}
const oldNames={revenue_ttm:'revenue',net_profit_ttm:'net_profit',operating_cash_flow_ttm:'operating_cash_flow'};
for(const f of core){
  const old=prior.fields.find(r=>r.dsl_identifier===oldNames[f.dsl_identifier]);
  if(!old || old.source_endpoint!==f.source_endpoint || old.source_column!==f.source_column)throw Error('Core TTM source mismatch');
  if(!evidence.financial_source_fields[f.source_endpoint].fields.includes(f.source_column))throw Error('Unsaved core source');
}
if(fields.length!==226 || fields.filter(r=>r.report_period_selection==='latest_visible_ttm').length!==19)throw Error('Count mismatch');
for(const f of fields){
  if(f.source_endpoint==='daily_basic' && ['dv_ratio','dv_ttm'].includes(f.source_column))f.note=f.note.replace('百分数；','来源百分数，DSL 使用小数比例（15% 为 0.15）；');
}
let md=fs.readFileSync('docs/research/dsl-field-catalog-223-2026-09-12.md','utf8');
md=md.replace('# 新版 223 个 DSL 字段目标清单','# 新版 226 个 DSL 字段目标清单');
md=md.replace('> 用户已确定新版目标：原方案 191 个字段，加上已保存三表中的 32 个扩展字段，共 223 个。本文定义待实施清单，32 项的名称与期间按本版设计建议列出；不表示已采集、已发布或覆盖已全部验收。',
'> 用户在 grill 中确认新版目标为 226 项：原方案 191 项、三表扩展 32 项、核心流量 TTM 3 项。新增 19 个流量采用显式 TTM；新百分比字段的 DSL 值采用小数比例。本文是待实施合同，来源单位、期间与覆盖仍须逐项验收。');
md=md.replace('| **合计** | **223** | **新增 211 个 DSL 入口** |','| 核心流量 TTM | 3 | 营业总收入、归母净利润、经营现金流；原年报字段保持 |\n| **合计** | **226** | **新增 214 个 DSL 入口** |');
md=md.replaceAll('不代表 223 个独立经济信息维度','不代表 226 个独立经济信息维度');
md=md.replace('设计：[223 字段接入方案]','设计：[226 字段接入方案]');
md=md.replace('原始 191 项范围保留在[前一版清单](dsl-field-catalog-2026-09-12.md)。','前两轮范围分别保留在 [191 项清单](dsl-field-catalog-2026-09-12.md)和 [223 项清单](dsl-field-catalog-223-2026-09-12.md)，当前以本 226 项清单为准。');
md=md.replace('## 名称和语义','## 名称和语义\n\n用户确认：新百分比类字段统一采用小数比例，15% 在 DSL 中为 0.15，界面可显示 15%。PE/PB 等倍数不除以 100；来源已是小数比例时也不重复换算。源尺度必须逐列核实，原始返回值保留。');
for(const f of fields.filter(r=>r.source_endpoint==='daily_basic' && ['dv_ratio','dv_ttm'].includes(r.source_column))){
  const old=prior.fields.find(r=>r.dsl_identifier===f.dsl_identifier);
  const originalNote=old.note.replace('来源百分数，DSL 使用小数比例（15% 为 0.15）；','百分数；');
  md=md.replace(originalNote,f.note);
}
const q=value=>String.fromCharCode(96)+value+String.fromCharCode(96);
const table=[
'## 核心流量新增 TTM：3 个','',
'三项重构使用原年报字段相同的科目和合并/归母范围，仅增加独立的最近十二个月口径。', '',
'| DSL 字段 | 中文含义 | TuShare 接口.列 | 口径说明 |','| --- | --- | --- | --- |',
...core.map(r=>'| '+q(r.dsl_identifier)+' | '+r.label+' | '+q(r.source_endpoint+'.'+r.source_column)+' | '+r.note+' |'),''
].join('\n');
md=md.replace('## 与来源名称不同的 DSL 名',table+'\n## 与来源名称不同的 DSL 名');
md=md.replace('本版三表来源字段为 38 个（原有 6 个加新增 32 个），新增流量包含显式 TTM 重构。额外的原始单季流量、披露年龄、新行业/交易状态字段和另列的 3 个银行专用字段不计入当前 223 基线；三个核心流量的额外 TTM 入口正在 grill 第二轮讨论。',
'本版三表来源字段为 41 个（原有 6 个、扩展 32 个、核心 TTM 3 个），其中新增 19 个流量使用显式 TTM 重构。额外的原始单季流量、披露年龄、新行业/交易状态字段和另列的 3 个银行专用字段不计入这 226 个。');
md=md.replace('所有值来自供应商；本轮不额外推导源接口没有独立提供的 '+q('revenue_ttm')+'、'+q('net_profit_ttm')+'、'+q('operating_cash_flow_ttm')+' 等字段。',
'本节 163 项直接保留供应商定义。另列的 19 个三表 TTM 字段由本系统按可见报告重构，不能与供应商定义混为同一来源。');
md=md.replace('dsl-field-catalog-223-2026-09-12.csv','dsl-field-catalog-226-2026-09-12.csv');
md+='\nTTM 使用可见的 本期累计 + 上年度全年 - 上年同期累计；年末直接取全年值，必要组成缺失则缺失。不能用 252 个交易日的财务填充值求和。核心 TTM 与旧年报字段虽复用同一源科目，但期间语义不同，因此是独立入口。\n';
md+='\n用户已确认：两个 TTM 流量直接运算时，覆盖的十二个月窗口不一致就返回缺失，不回退到旧报告来凑齐期间；双方以后完整且同窗口时，从当时可见日恢复计算。结果沿用现有缺失传播和覆盖统计，不增加期间差异界面。这不会给原有字段公式、常数、行情、存量或显式跨期计算追加统一报告日限制。见 [ADR-0246](../adr/0246-return-missing-for-misaligned-ttm-flow-arithmetic.md)。\n';
const out='docs/research/dsl-field-catalog-226-2026-09-12.md';
fs.writeFileSync(out,md);
const headers=['status','group','dsl_identifier','label','source_endpoint','source_column','report_period_selection','proposed_field_id','note'];
const cell=value=>'"'+String(value??'').replace(/"/g,'""')+'"';
fs.writeFileSync('docs/research/dsl-field-catalog-226-2026-09-12.csv',[headers.map(cell).join(','),...fields.map(r=>headers.map(k=>cell(r[k])).join(','))].join('\n')+'\n');
fs.writeFileSync(base+'/dsl-field-inventory-226.json',JSON.stringify({scope:'user_confirmed_226_target_design',total:226,existing:12,additions:214,counts:{existing:12,daily_basic:16,fina_indicator:163,additional_statements:32,core_ttm:3},new_flow_period:'TTM',new_percentage_alpha_representation:'decimal_ratio_after_source_unit_verification',ttm_flow_arithmetic_period_policy:'missing_on_window_mismatch',fields},null,2)+'\n');
console.log(JSON.stringify({total:226,new_ttm_fields:19,existing_12_preserved:true,identifiers_unique:true,core_source_match:true,artifact:path.resolve(out)},null,2));
