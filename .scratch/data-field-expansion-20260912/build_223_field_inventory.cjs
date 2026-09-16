const fs = require('node:fs');
const path = require('node:path');
const base = '.scratch/data-field-expansion-20260912';
const baseline = JSON.parse(fs.readFileSync(base + '/dsl-field-inventory.json', 'utf8'));
const additional = JSON.parse(fs.readFileSync(base + '/statement-extension-32.json', 'utf8')).fields;
const evidence = JSON.parse(fs.readFileSync(base + '/production-mounted-evidence.json', 'utf8'));
const fields = [...baseline.fields, ...additional];
const builtins = new Set(['abs','log','sign','rank','lag','delta','pct_change','ts_mean','ts_sum','ts_std','ts_min','ts_max']);
const identifiers = new Set(builtins);
for (const field of fields) {
  if (!/^[a-z][a-z0-9_]*$/.test(field.dsl_identifier) || identifiers.has(field.dsl_identifier)) throw Error('Invalid identifier: ' + field.dsl_identifier);
  identifiers.add(field.dsl_identifier);
}
const sourceKeys = new Set(baseline.fields.map(r => r.source_endpoint + '.' + r.source_column));
for (const field of additional) {
  const key = field.source_endpoint + '.' + field.source_column;
  if (sourceKeys.has(key) || !evidence.financial_source_fields[field.source_endpoint].fields.includes(field.source_column)) throw Error('Invalid additional source: ' + key);
  sourceKeys.add(key);
}
if (baseline.total !== 191 || additional.length !== 32 || fields.length !== 223) throw Error('Count mismatch');
if (additional.filter(r => r.period_kind === 'stock').length !== 16 || additional.filter(r => r.period_kind === 'flow').length !== 16) throw Error('Period count mismatch');
const q = value => String.fromCharCode(96) + value + String.fromCharCode(96);
const rowTable = rows => [
  '| DSL 字段 | 中文含义 | TuShare 接口.列 | 口径说明 |',
  '| --- | --- | --- | --- |',
  ...rows.map(r => '| ' + q(r.dsl_identifier) + ' | ' + r.label + ' | ' + q(r.source_endpoint + '.' + r.source_column) + ' | ' + r.note + ' |')
].join('\n');
let md = fs.readFileSync('docs/research/dsl-field-catalog-2026-09-12.md', 'utf8');
md = md.replace('# 本轮 DSL 字段完整目标清单', '# 新版 223 个 DSL 字段目标清单');
md = md.replace('> 范围：保留现有 12 个字段，接入 daily_basic 和 fina_indicator，开放两接口的数值字段。本文是待实施清单，不表示新字段已上线；不是所有已存三表原始列的开放计划。',
'> 用户已确定新版目标：原方案 191 个字段，加上已保存三表中的 32 个扩展字段，共 223 个。本文定义待实施清单，32 项的名称与期间按本版设计建议列出；不表示已采集、已发布或覆盖已全部验收。');
md = md.replace('| **合计** | **191** | **新增 179 个 DSL 入口** |', '| 三表原始金额扩展 | 32 | 拟新增；16 个存量、16 个 TTM 流量 |\n| **合计** | **223** | **新增 211 个 DSL 入口** |');
md = md.replace('不代表 191 个独立经济信息维度', '不代表 223 个独立经济信息维度');
md = md.replace('## 名称和语义', '设计：[223 字段接入方案](../../.scratch/data-field-expansion-20260912/spec.md)。原始 191 项范围保留在[前一版清单](dsl-field-catalog-2026-09-12.md)。\n\n## 名称和语义');
md = md.replace('## 与来源名称不同的 DSL 名', [
  '## 已保存三表新增：32 个', '',
  '新增 32 项以已保存三表为来源：16 个存量取最新可见报告期，16 个流量按用户在 grill 中确认的 TTM 口径重构，名称带 _ttm。TTM 只组合当时可见且期间匹配的报告，必要组成缺失则缺失。', '',
  '### 最新报告期存量：16 个', '', rowTable(additional.filter(r => r.period_kind === 'stock')), '',
  '### 显式 TTM 流量：16 个', '', rowTable(additional.filter(r => r.period_kind === 'flow')), '',
  'cash_equivalents 来自现金流量表，但它是期末存量。不能根据所在报表把它当全年现金流或做 TTM 求和。', '',
  '来源：[三表扩展核查](three-statement-field-extensions-2026-09-12.md)。目标金额单位为人民币元，接入前逐项确认源单位与覆盖。', '',
  '## 与来源名称不同的 DSL 名'
].join('\n'));
md = md.replace('所有三表已存原始列不会因此自动全部开放。本轮保留原有六个三表字段，新增入口以本表为准。自算 TTM、原始单季收入/利润/经营现金流、披露年龄、新行业/交易状态字段不计入这 191 个。',
'本版三表来源字段为 38 个（原有 6 个加新增 32 个），新增流量包含显式 TTM 重构。额外的原始单季流量、披露年龄、新行业/交易状态字段和另列的 3 个银行专用字段不计入当前 223 基线；三个核心流量的额外 TTM 入口正在 grill 第二轮讨论。');
md = md.replace('- [逐字段 CSV](dsl-field-catalog-2026-09-12.csv)', '- [逐字段 CSV](dsl-field-catalog-223-2026-09-12.csv)');
md += '\n32 个新增来源列已逐项对照生产保存列清单核验，无直接来源列重复；这不等于全公司全历史非空保证。\n';
const file = 'docs/research/dsl-field-catalog-223-2026-09-12.md';
fs.writeFileSync(file, md);
const headers = ['status','group','dsl_identifier','label','source_endpoint','source_column','report_period_selection','proposed_field_id','note'];
const csvCell = value => '"' + String(value ?? '').replace(/"/g, '""') + '"';
fs.writeFileSync('docs/research/dsl-field-catalog-223-2026-09-12.csv', [headers.map(csvCell).join(','), ...fields.map(r => headers.map(k => csvCell(r[k])).join(','))].join('\n') + '\n');
fs.writeFileSync(base + '/dsl-field-inventory-223.json', JSON.stringify({scope:'accepted_223_target_design', total:223, existing:12, additions:211, counts:{existing:12,daily_basic:16,fina_indicator:163,additional_statements:32}, fields}, null, 2) + '\n');
console.log(JSON.stringify({total:223,unique_identifiers:fields.length,additional_saved_sources:32,stocks:16,annual_flows:16,artifact:path.resolve(file)},null,2));
