const fs=require('node:fs'),path=require('node:path');
const base='.scratch/data-field-expansion-20260912';
const schema=JSON.parse(fs.readFileSync(base+'/official-field-schema.json','utf8'));
const descriptions=JSON.parse(fs.readFileSync(base+'/fina-indicator-dsl-descriptions.json','utf8'));
const descriptionRows=Array.isArray(descriptions)?descriptions:descriptions.fields;
const live=JSON.parse(fs.readFileSync(base+'/live-tushare-field-probe.json','utf8'));
const existing=[
['open','复权开盘价','daily','open','交易日；结合 adj_factor 得到复权值'],
['high','复权最高价','daily','high','交易日；结合 adj_factor 得到复权值'],
['low','复权最低价','daily','low','交易日；结合 adj_factor 得到复权值'],
['close','复权收盘价','daily','close','交易日；结合 adj_factor 得到复权值，保持原有含义'],
['volume','成交股数','daily','vol','交易日；已规范为股'],
['amount','成交金额','daily','amount','交易日；已规范为人民币元'],
['revenue','营业总收入','income','total_revenue','最新可见年报；不是营业收入列，也不是 TTM'],
['net_profit','归母净利润','income','n_income_attr_p','最新可见年报；不是 TTM'],
['operating_cash_flow','经营现金流净额','cashflow','n_cashflow_act','最新可见年报；不是 TTM'],
['assets','总资产','balancesheet','total_assets','最新可见季度或年度报告'],
['liabilities','总负债','balancesheet','total_liab','最新可见季度或年度报告'],
['equity','归母股东权益','balancesheet','total_hldr_eqy_exc_min_int','最新可见季度或年度报告；不含少数股东权益']
].map(([dsl_identifier,label,source_endpoint,source_column,note])=>({status:'现有',group:'现有字段',dsl_identifier,label,source_endpoint,source_column,note}));
const daily=[
['close_raw','未复权收盘价','close','元/股。已有行情也保存原始价，实施时复用 price.close.raw 身份并核对来源一致性。'],
['total_mv','总市值','total_mv','来源万元；DSL 规范为人民币元。'],
['circ_mv','流通市值','circ_mv','来源万元；DSL 规范为人民币元。'],
['total_share','总股本','total_share','来源万股；DSL 规范为股。'],
['float_share','无限售流通股本','float_share','来源万股；DSL 规范为股。'],
['free_share','自由流通股本','free_share','来源万股；DSL 规范为股；不同于 float_share。'],
['turnover_rate','无限售流通股换手率','turnover_rate','分母为无限售流通股数；比例缩放结合实际量/股本样本锁定。'],
['turnover_rate_f','自由流通股换手率','turnover_rate_f','分母为自由流通股数；不与 turnover_rate 合并。'],
['volume_ratio','供应商量比','volume_ratio','保留供应商值；文档未明确完整均值窗口。'],
['pe','供应商年度市盈率','pe','倍数；亏损时来源可为空。'],
['pe_ttm','供应商 TTM 市盈率','pe_ttm','倍数；不等于已提供独立的 net_profit_ttm。'],
['pb','供应商市净率','pb','倍数；供应商净资产分母扣除其他权益工具。'],
['ps','供应商年度市销率','ps','倍数；分母为最新年度营业收入。'],
['ps_ttm','供应商 TTM 市销率','ps_ttm','倍数；保留供应商定义。'],
['dv_ratio','供应商年度股息率','dv_ratio','百分数；上一年发生除息的派现口径。'],
['dv_ttm','供应商滚动股息率','dv_ttm','百分数；除息日和分红报告期均有供应商近 12 个月约束。']
].map(([dsl_identifier,label,source_column,note])=>({status:'拟新增',group:'每日指标',dsl_identifier,label,source_endpoint:'daily_basic',source_column,note}));
const overrides={
gross_margin:'gross_profit',grossprofit_margin:'gross_profit_margin',netprofit_margin:'net_profit_margin',
interst_income:'interest_expense',bps_yoy:'bps_ytd_growth',assets_yoy:'assets_ytd_growth',
eqt_yoy:'equity_parent_ytd_growth',cfps_yoy:'ocfps_yoy',q_gsprofit_margin:'q_gross_profit_margin',q_netprofit_margin:'q_net_profit_margin'
};
const financial=descriptionRows.map(r=>({status:'拟新增',group:r.group,dsl_identifier:overrides[r.source_column]||r.source_column,label:r.label,source_endpoint:'fina_indicator',source_column:r.source_column,note:r.note||r.semantic_note||''}));
const equal=(a,b)=>JSON.stringify([...a].sort())===JSON.stringify([...b].sort());
for(const [name,rows] of [['daily_basic',daily],['fina_indicator',financial]]){
 const wanted=schema[name].filter(r=>r.type==='float').map(r=>r.name);
 const got=live.results.find(r=>r.endpoint===name);
 if(!equal(rows.map(r=>r.source_column),wanted)||got.source_code!==0||wanted.some(n=>!got.returned_fields.includes(n)))throw Error('Source inventory mismatch: '+name);
}
const rows=[...existing,...daily,...financial];
const builtinNames=['abs','log','sign','rank','lag','delta','pct_change','ts_mean','ts_sum','ts_std','ts_min','ts_max'];
const seen=new Set(builtinNames);
for(const r of rows){
 if(!/^[a-z][a-z0-9_]*$/.test(r.dsl_identifier)||seen.has(r.dsl_identifier)||!r.label||!r.group)throw Error('Invalid field: '+r.dsl_identifier);
 seen.add(r.dsl_identifier);
}
if(existing.length!==12||daily.length!==16||financial.length!==163||rows.length!==191)throw Error('Wrong counts');
const counts=Object.fromEntries([...new Set(financial.map(r=>r.group))].map(g=>[g,financial.filter(r=>r.group===g).length]));
const tick=s=>String.fromCharCode(96)+s+String.fromCharCode(96);
const esc=s=>String(s).replace(/\|/g,'\\|').replace(/\r?\n/g,' ');
const table=(rs,endpoint=false)=>[
'| DSL 字段 | 中文含义 | TuShare '+(endpoint?'接口.列':'来源列')+' | 口径说明 |','| --- | --- | --- | --- |',
...rs.map(r=>'| '+tick(r.dsl_identifier)+' | '+esc(r.label)+' | '+tick(endpoint?r.source_endpoint+'.'+r.source_column:r.source_column)+' | '+esc(r.note||'沿用该供应商指标定义。')+' |')
].join('\n');
const md=[
'# 本轮 DSL 字段完整目标清单','',
'> 范围：保留现有 12 个字段，接入 daily_basic 和 fina_indicator，开放两接口的数值字段。本文是待实施清单，不表示新字段已上线；不是所有已存三表原始列的开放计划。',
'> 本次只更新清单，不执行采集、发布或应用代码修改。','',
'| 范围 | 数量 | 状态 |','| --- | ---: | --- |',
'| 原有行情 | 6 | 已开放，含义保持不变 |',
'| 原有三表财务 | 6 | 已开放，含义保持不变 |',
'| daily_basic 数值字段 | 16 | 拟新增；原始收盘价复用已有数据身份 |',
'| fina_indicator 数值字段 | 163 | 拟新增 |',
'| **合计** | **191** | **新增 179 个 DSL 入口** |','',
'数量按不同 DSL 名计，不代表 191 个独立经济信息维度，也不代表每个股票/报告期都有值。元数据不计入。','',
'## 名称和语义','',
'- 延续当前全局唯一的小写 snake_case 名，例如 '+tick('rank(roe) - rank(pb)')+'；不引入当前编译器不接受的点号访问。',
'- 原有 '+tick('revenue')+'、'+tick('net_profit')+'、'+tick('operating_cash_flow')+' 保留最新可见年报含义，不改成累计、单季或 TTM。',
'- 新字段尽量沿用常用来源名称；下文对毛利金额、利息费用、较年初增长等易误读名称作一对一调整，不同时提供别名。',
'- fina_indicator 字段标注为供应商指标。季度、同比、较年初、年化、加权等口径分别解释，不假设所有指标都是 TTM；不在源字段为空时改用三表自算值。',
'- 清单锁定拟开放的名称、来源和含义。市值/股本按官方明确单位转换；其他字段在接入时逐项核对金额、倍数、百分数和适用范围，不统一除以 100。单位和覆盖验证通过后才发布。','',
'依据：[当前字段定义](../../apps/core/src/thesistrace/data/fields.py)、[作者名称与内部引用分离](../adr/0191-separate-authoring-identifiers-from-canonical-field-references.md)、[不可变字段语义](../adr/0014-keep-canonical-field-definitions-immutable.md)。','',
'## 现有字段：12 个','',table(existing,true),'',
'## daily_basic：16 个','',
'包含该接口全部 16 个 float 列。'+tick('close_raw')+' 是未复权价格，原有 '+tick('close')+' 是复权价格；不覆盖原名。已有行情也保存原始收盘价，实施时复用既有 Canonical 身份并核验来源一致性。','',
table(daily),'',
'来源：[daily_basic 官方文档](https://tushare.pro/document/2?doc_id=32)。','',
'## fina_indicator：163 个','',
'按研究用途逐项分组。所有值来自供应商；本轮不额外推导源接口没有独立提供的 '+tick('revenue_ttm')+'、'+tick('net_profit_ttm')+'、'+tick('operating_cash_flow_ttm')+' 等字段。','',
'| 类别 | 数量 |','| --- | ---: |',
...Object.entries(counts).map(([g,n])=>'| '+g+' | '+n+' |'),
'| **合计** | **163** |',''
];
for(const [g,n]of Object.entries(counts))md.push('### '+g+'（'+n+'）','',table(financial.filter(r=>r.group===g)),'');
md.push(
'来源：[fina_indicator 官方文档](https://tushare.pro/document/2?doc_id=79)。中文含义为文档事实的简述，不表示已独立复算供应商公式或确认所有字段的历史覆盖。','',
'## 与来源名称不同的 DSL 名','',
'| DSL 名 | 来源列 | 区分原因 |','| --- | --- | --- |',
'| '+tick('gross_profit')+' | '+tick('gross_margin')+' | 来源指毛利金额，不是毛利率。 |',
'| '+tick('gross_profit_margin')+' | '+tick('grossprofit_margin')+' | 毛利率，与金额分开。 |',
'| '+tick('net_profit_margin')+' | '+tick('netprofit_margin')+' | 统一单词分隔。 |',
'| '+tick('interest_expense')+' | '+tick('interst_income')+' | 文档定义为利息费用。 |',
'| '+tick('bps_ytd_growth')+' | '+tick('bps_yoy')+' | 每股净资产相对年初增长。 |',
'| '+tick('assets_ytd_growth')+' | '+tick('assets_yoy')+' | 总资产相对年初增长。 |',
'| '+tick('equity_parent_ytd_growth')+' | '+tick('eqt_yoy')+' | 归母权益相对年初增长。 |',
'| '+tick('ocfps_yoy')+' | '+tick('cfps_yoy')+' | 文档定义为每股经营现金流同比。 |',
'| '+tick('q_gross_profit_margin')+' | '+tick('q_gsprofit_margin')+' | 统一毛利率名称，保留单季口径。 |',
'| '+tick('q_net_profit_margin')+' | '+tick('q_netprofit_margin')+' | 统一净利率名称，保留单季口径。 |','',
'这些调整仅针对拟新增字段，不改动现有名称。','',
'## 保存但不直接作为数值因子的字段','',
'| 来源 | 字段 | 用途 |','| --- | --- | --- |',
'| daily_basic | '+tick('ts_code')+'、'+tick('trade_date')+' | 证券和日期关联。 |',
'| daily_basic | '+tick('limit_status')+' | 分类码，0–6 不表示连续经济量；本轮不按普通数值字段开放。 |',
'| fina_indicator | '+tick('ts_code')+'、'+tick('ann_date')+'、'+tick('end_date')+'、'+tick('update_flag')+' | 证券、报告期、可见时间、版本处理。 |','',
'所有三表已存原始列不会因此自动全部开放。本轮保留原有六个三表字段，新增入口以本表为准。自算 TTM、原始单季收入/利润/经营现金流、披露年龄、新行业/交易状态字段不计入这 191 个。','',
'## 发布与使用要求','',
'- daily_basic 按交易日读取，收盘后数据用于后续执行，不进入同日开盘决策。',
'- fina_indicator 先选择当时已可见的来源版本，再按报告期取值；不能在报告期结束当天提前使用。选中版本中缺失的列保持缺失，不按列回退旧报告或填零。',
'- 原始输出列连同身份、日期和更新标记都需保存。字段目录、Generation 可用字段和研究准入同步发布；回测与 DailyTrack 使用同一合同。',
'- 现有研究保留原 Generation。样本请求成功证明权限和字段形状，不证明全历史非空覆盖；新增字段经过单位、覆盖和历史可见性验证后发布。','',
'新增字段接入后的公式示例：','',
'~~~text','rank(roe) - rank(pb)','rank(netprofit_yoy) + rank(ocf_yoy)','rank(roe) - rank(debt_to_assets)','-rank(total_mv) + rank(amount)','rank(q_netprofit_yoy) + rank(q_roe)','rank(dv_ttm) - rank(pe_ttm)','~~~','',
'示例依赖尚未上线的新字段，当前运行环境仍只有原有 12 个字段。','',
'## 核验依据','',
'2026-09-12 使用生产现有账户进行小样本读取：daily_basic 返回全部 19 个输出列、fina_indicator 返回全部 167 个输出列，其中 float 列分别为 16 和 163。本清单已对齐全部 float 列，并检查 DSL 名合法性、唯一性及与 Builtin 的冲突。','',
'- [实际接口字段探针](../../.scratch/data-field-expansion-20260912/live-tushare-field-probe.json)',
'- [官方字段名称与类型](../../.scratch/data-field-expansion-20260912/official-field-schema.json)',
'- [生产现有 DSL 字段](../../.scratch/data-field-expansion-20260912/runtime-evidence.json)',
'- [逐字段 CSV](dsl-field-catalog-2026-09-12.csv)',
'- [完整扩展研究](tushare-field-expansion-2026-09-12.md)',''
);
const headers=['status','group','dsl_identifier','label','source_endpoint','source_column','note'];
const cell=s=>'"'+String(s).replace(/"/g,'""')+'"';
const csv=[headers.map(cell).join(','),...rows.map(r=>headers.map(k=>cell(r[k]||'')).join(','))].join('\n')+'\n';
fs.writeFileSync('docs/research/dsl-field-catalog-2026-09-12.md',md.join('\n'));
fs.writeFileSync('docs/research/dsl-field-catalog-2026-09-12.csv',csv);
fs.writeFileSync(base+'/dsl-field-inventory.json',JSON.stringify({scope:'proposed_current_12_plus_two_new_sources',total:rows.length,counts,fields:rows},null,2)+'\n');
console.log(JSON.stringify({total:rows.length,existing:12,new_daily:16,new_financial:163,counts,identifiers_valid_and_unique:true,source_sets_match:true},null,2));
