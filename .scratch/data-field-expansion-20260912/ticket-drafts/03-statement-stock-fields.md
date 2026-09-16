# 03 — 开放三表的 16 个期末存量字段

**What to build:** Researcher 能直接组合应收、存货、现金和负债余额研究资产负债结构；数据复用已存三表原始记录，并在正确公告可见时间进入原有 Financial data 区块和研究公式。

**Blocked by:** 01 — 统一现有字段目录、准入和家族合同

**Status:** needs-triage

**Draft:** 拆分待确认，尚未发布。

- [ ] 按权威清单开放 monetary_funds、accounts_receivable、notes_receivable、other_receivables、prepayments、inventories、accounts_payable、contract_assets、contract_liabilities、goodwill、short_term_borrowings、long_term_borrowings、bonds_payable、noncurrent_liabilities_due_1y、other_equity_instruments、cash_equivalents，共 16 项，归入 equity.financial_pit。
- [ ] 逐列核实源科目、CNY 单位、合并范围和公司类型适用性，保持每个 Canonical Field 的独立定义。货币资金不自动解释为无限制现金，一年内到期非流动负债不自动等于全部有息债务。
- [ ] 每项按固定期间合同选择最新可见报告的期末余额；cash_equivalents 虽来自现金流量表也按存量处理，不能被年报流量过滤或转换成 TTM。选中报告该列为空就缺失，不寻找旧非空值或相近来源列。
- [ ] 从已保存原始证据生成新投影，并保留现有 6 个财务字段语义、原始版本和所需种子。只有可证明的原始记录缺口才补采，不默认重新下载三张报表。
- [ ] 必要的 pre-start 期末种子可在声明 Coverage 起点正确读取，包括来自现金流量表的存量；保留原年报/存量种子，不允许由此提交 pre-2010 研究，历史退市证券仍使用相同身份。
- [ ] 无有效公告日期的记录隔离；有效日期从下一 Research Session 可用。保留原始值、首次观察和版本证据；去重不抹掉最早观察，后见更正不回填过去，无法排序的冲突不能按响应顺序选胜者。
- [ ] Financial Refresh 在保留既有来源证据的前提下更新这些字段，并保留其他家族及其覆盖。来源未完成、原值缺失与不适用分别记录，不通过填零制造可用性。
- [ ] 目录、Financial data、公式补全、HTTP/MCP 和 Agent 展示一致的中文含义、单位、来源、期间和实际覆盖；不新增顶层卡片或逐日财务期间界面。
- [ ] 用最新报告空值、现金流量表期末余额、公告日边界和修订 Fixture 验证读取；演示一个存量与原有 assets 组合的公式从目录发现到研究完成，并证明旧 Generation 不会被赋予这些新字段。

**Verification:** 母规格 T01、T02、T04、T06、T07、T09、T11、T15 的存量部分。与 04 无业务前置关系；两票集成后共同组成扩展的三表家族。本票不单独上线。
