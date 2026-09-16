# 04 — 提供 19 个 TTM 流量及不同期缺失规则

**What to build:** Researcher 能用明确的最近十二个月流量研究收入、利润和现金流；系统从可见三表重构 TTM，组成缺失或两个 TTM 直接运算的窗口不同就沿用现有缺失行为，无需新增前端期间差异展示。

**Blocked by:** 01 — 统一现有字段目录、准入和家族合同

**Status:** needs-triage

**Draft:** 拆分待确认，尚未发布。

- [ ] 接入三项核心字段 revenue_ttm、net_profit_ttm、operating_cash_flow_ttm，以及权威三表扩展清单的 16 项 TTM：cash_paid_capex_ttm、cash_received_sales_ttm、cash_paid_goods_ttm、cash_received_asset_disposals_ttm、cash_paid_acquisitions_ttm、cash_paid_investments_ttm、cash_received_borrowing_ttm、cash_paid_debt_repayment_ttm、operating_revenue_ttm、consolidated_net_profit_ttm、operating_cost_ttm、rd_expense_ttm、investment_income_ttm、fair_value_gain_ttm、nonoperating_income_ttm、nonoperating_expense_ttm。
- [ ] 原 revenue、net_profit、operating_cash_flow 仍取最新可见年报。三个核心 TTM 分别沿用原收入、归母和合并现金流范围；营业收入与总收入、合并与归母利润、研发费用与供应商研发投入保持独立含义。逐列有来源、单位、合并范围和适用性证据。
- [ ] 对各字段独立选择最新可见目标报告，年末直接取全年；中期取本期累计加上年全年减上年同期累计。股票、源科目、单位、报告范围和可见版本必须匹配，不能将每日填充序列滚动求和。
- [ ] 任何组成记录或值缺失就返回缺失，不退到旧报告、年报、上一期 TTM 或其他来源；本期、上年全年、上年同期任一可见更正都触发重算。后来的完整数据或修订不能改写之前 Session。
- [ ] 从已存原始报表重建投影，只有确证缺口才补采。种子覆盖整个声明 Coverage 所需 pre-start 依赖闭包，并与原年报/存量种子取并集；起点可能需要 2008 年报/三季报，计算 2010 一季报仍保留所需 2009 一季报，不扩大研究起始边界。
- [ ] Data 返回 Numeric Series 时附带同期判断所需的最小期间信息；组成和供应商证据留在 Data。两个 TTM 流量直接算术运算时，只有双方有效且十二个月窗口一致才计算，否则该股票日的运算缺失。
- [ ] 括号、正负号及乘除常数不能绕过应有的同期检查。单字段仍选自己的最新报告；常数、每日行情、期末存量、原有公式、显式跨期 Builtin 和截面排名保留现有语义，不增加全公式或全市场统一报告日限制。
- [ ] 以独立预期验证本期 60、上年全年 100、上年同期 50 得到 110；全年更正为 105 后，仅从更正可见日起得到 115。另覆盖年报直取、必要项缺失、目标为空、跨来源范围不同及首年后续种子。
- [ ] 同窗 TTM 运算有结果，三月底与六月底窗口运算缺失，并覆盖列式执行中的括号和常数变形。单次、Batch、DailyTrack 使用同一读取和对齐逻辑，缓存不跨 Generation，研究不联网补取。
- [ ] 最终 Alpha 缺失不进入有效样本或排序，沿用 missing_expression、现有样本门槛和调仓规则；普通缺失日不产生即时交易，也不被当成零。经营现金流减资本支出不自动命名为严格 FCFF/FCFE。
- [ ] 19 项能在 Financial data、补全、HTTP/MCP 和 Agent 中按其固定 TTM 含义查询和提交；演示一个同窗组合公式以及不同窗时的既有缺失结果，不增加期间差异 UI。
- [ ] 后续 Financial Refresh 保留来源版本、TTM 所需组成与其他家族；公开计算、真实文件候选重开、受影响合同和关键研究路径的验证通过。

**Verification:** 母规格 T01、T02、T03、T04、T05、T06、T07、T10、T14、T15。与 03 无业务前置关系；本票完整拥有 TTM 读取到表达式缺失的边界，不拆成只有计算或只有前端的任务，不单独上线。
