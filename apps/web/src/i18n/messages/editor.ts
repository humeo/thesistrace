export const editorEn = {
  formula: "Alpha formula", exposure: "Exposure expression", formulaEditor: "Alpha formula editor", exposureEditor: "Exposure formula editor",
  placeholder: "Start with a field or function", exposurePlaceholder: "1 or if_else(universe_return() > 0, 1, 0.3)",
  booleanOperator: "Boolean operator; unknown values remain unknown", numericSeries: "Numeric series",
  industryHelp: "Historical industry subset of the selected research Universe; not an official index.",
  canonicalField: "Canonical field: {{id}}",
  phrases: { Completions: "Completions", Diagnostics: "Diagnostics", "No diagnostics": "No diagnostics", close: "close", "Control character": "Control character" },
} as const;
export const editorZh = {
  formula: "Alpha 公式", exposure: "仓位表达式", formulaEditor: "Alpha 公式编辑器", exposureEditor: "仓位公式编辑器",
  placeholder: "从字段或函数开始", exposurePlaceholder: "1 或 if_else(universe_return() > 0, 1, 0.3)",
  booleanOperator: "布尔运算符；未知值仍为未知", numericSeries: "数值序列",
  industryHelp: "所选研究股票池的历史行业子集；不是官方指数。",
  canonicalField: "规范字段：{{id}}",
  phrases: { Completions: "补全建议", Diagnostics: "诊断", "No diagnostics": "没有诊断问题", close: "关闭", "Control character": "控制字符" },
} satisfies { [K in keyof typeof editorEn]: K extends "phrases" ? Record<keyof typeof editorEn.phrases, string> : string };
