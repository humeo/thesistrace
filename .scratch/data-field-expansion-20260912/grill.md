# 字段设计 Grill：决定树与核查记录

状态：grill 的产品选择已收敛，目标 226；讨论已合成为 [正式规格](spec.md)，其状态为 ready-for-agent。本文保留决定和核查过程，不另定义实施范围。来源资格、应用实现和验收尚未完成。

## 已确认的根约束

- 原有 12 个字段的含义保留；复用既有行情和三表原始证据。
- 单一 DSL 作者入口与 Data 权威字段目录；不在研究执行时请求 TuShare。
- 缺失值不能填零或用其他来源/期间替代。真正缺失的数据不产生该次计算值。
- 按用户提出的硬切和架构整洁要求，一次切换到当前合同；历史数据与研究快照保留，由同一套规则读取，不维护新旧运行实现。

## 第一轮

| 编号 | 问题 | 用户决定 | 文档落实 |
| --- | --- | --- | --- |
| Q1 | 新增 16 个流量的期间 | 支持 TTM；原年报字段不变 | spec 的 TTM 合同、32 项定义、ADR-0243、CONTEXT |
| Q2 | 缺少完整历史修订链的供应商历史是否可研究 | 允许回填，明确历史证据范围 | spec、ADR-0244、CONTEXT |

## 第二轮

| 编号 | 问题 | 用户回应 | 当前结论 |
| --- | --- | --- | --- |
| Q3 | 是否增加三个核心流量 TTM | 补齐，总数 226 | revenue_ttm、net_profit_ttm、operating_cash_flow_ttm 加入；原年报入口保留 |
| Q4 | 不同报告期的现成值能否直接组合 | “不要这么复杂，还会影响前端，直接表示缺失又会怎么样呢？” | 两个 TTM 流量直接组合时，不同窗口返回缺失；沿用缺失传播和覆盖统计，不增加期间差异前端；spec、ADR-0246 |
| Q5 | 新百分比 Alpha 字段的表示 | DSL 使用 0.15，界面显示 15% | spec、226 清单、ADR-0245；源单位仍需逐列核实 |

## 决定树

~~~mermaid
flowchart TD
  Goal[字段研究能力] --> Scope[目标 226：已确认]
  Scope --> Period[新增流量 TTM：已确认]
  Period --> Core[三个核心 TTM 补齐：已确认]
  Period --> TTM[匹配可见组成报告；缺项缺失]
  TTM --> Seed[覆盖内所有目标期的依赖 seed]
  TTM --> Revision[任一组成报告修订触发重算]
  Scope --> Evidence[允许公告日对齐历史；明确修订限制]
  Scope --> Units[百分比规范为小数比例：已确认]
  Scope --> Combine[两个 TTM 流量不同窗口：运算缺失]
  Combine --> Contract[后端检查窗口；沿用缺失处理]
  Contract --> Boundary[不增加期间差异界面]
  Scope --> Cutover[一次切换当前合同；保留历史数据]
  Scope --> Presentation[现有四个 Data 区块聚合新家族]
~~~

TTM 示例：2026 半年报后的最近十二个月为 2025 下半年加 2026 上半年，可用 2025 全年 + 2026 上半年 - 2025 上半年计算。这是报告期计算，不是交易日滚动求和。

Q4 的非空反例：营业收入 TTM 为 100 亿元，覆盖 2025-07 至 2026-06；资本支出 TTM 为 10 亿元，覆盖 2025-04 至 2026-03。按用户最终决定，这两个值的比值返回缺失；任意一项本身缺失时同样缺失。后续双方完整且窗口一致时，从当时可见日恢复计算，不改写过去。

## 已查明的工程事实

| 事实 | 当前证据 | 应加入的验收 |
| --- | --- | --- |
| 旧 Generation 的 readiness 依赖当前全局字段列表，扩容后可直接无法重开 | [根校验](../../apps/core/src/thesistrace/data/generation_store.py#L2630)、[字段声明](../../apps/core/src/thesistrace/data/generation_store.py#L2680) | 新代码重开旧根；旧公式重试；旧根拒绝新字段 |
| 当前 Numeric Series 只保留数值，丢弃实际报告期 | [输出模型](../../apps/core/src/thesistrace/research_series.py#L47)、[报告投影](../../apps/core/src/thesistrace/data/financial_series.py#L445) | 后端保留检查 TTM 窗口所需的最小信息，不增加期间差异展示合同 |
| 最终 Alpha 缺失已排除出信号，并记录 missing_expression | [Alpha 输出](../../apps/core/src/thesistrace/research_kernel/alpha.py#L202)、[调仓选股](../../apps/core/src/thesistrace/research_kernel/strategy.py#L433) | 复用缺失传播、有效样本与覆盖统计；缺失可能影响调仓选股，不新增即时交易规则 |
| 编译器只有数值形状类型，没有经济单位自动换算 | [类型](../../apps/core/src/thesistrace/alpha_language/models.py#L9)、[二元运算](../../apps/core/src/thesistrace/alpha_language/language.py#L326) | 用明确规范单位提供序列；不宣称新增量纲检查 |
| DailyTrack 固定 Origin 字段绑定，但每次 Attempt 使用它固定的数据版本 | [Origin](../../apps/core/src/thesistrace/daily_track/checkpoint.py#L289)、[Attempt](../../apps/core/src/thesistrace/daily_track/service.py#L2424) | 新版数据推进旧 Track，字段身份与原含义保持 |
| 当前 pre-start seed 按 endpoint 仅取一条，现金流仅年报 | [seed 选择](../../apps/core/src/thesistrace/data/financial_candidate.py#L1889) | 年报、存量、TTM 依赖闭包；后续首年季报所需的上年同期记录 |
| 当前行情刷新只显式保留行业和 financial_pit，尚未认识两个新增家族 | [刷新组合](../../apps/core/src/thesistrace/data/generation_store.py#L1412) | 新版首次发布后的行情、三表和行业刷新都保留非目标家族、新字段及各自覆盖 |
| Head 已切换后，完成回执仍可能失败 | [Head 比较切换](../../apps/core/src/thesistrace/data/head_store.py#L130)、[发布后回执](../../apps/core/src/thesistrace/data/financial_refresh.py#L228) | 切换前失败不发布；切换成功后对账补全任务状态，不误报旧 Head 仍在使用 |
| DataPage 按单一家族过滤类别，Overview 就绪只认识原行情与三表 | [页面分组](../../apps/web/src/data/DataPage.tsx#L59)、[就绪汇总](../../apps/core/src/thesistrace/data/overview.py#L105) | Market/Financial 多家族字段不漏项，部分就绪不假报全部 ready；沿用四个顶层区块 |
| Alpha 目录仅以一个财务布尔值决定开放字段 | [作者目录](../../apps/core/src/thesistrace/alpha_language/language.py#L109) | 硬切为当前 Generation 的实际可用字段集合，HTTP/MCP、Agent 与 Web 同源 |

用户追问新旧数据如何结合后，正式规格的“数据组合、发布与刷新”已明确复用范围、股票/研究日对齐、重复与更正处理、并发重组、原子切换以及旧研究的版本引用。此处沿用已确定的单一 Head 与不可变数据版本合同，不新增用户配置或替换策略选择。

用户指向 /data 的 Financial data、Industry data 卡片，并要求硬切保持架构整洁后，正式规格的“Data 页面与 Agent 体验”和“一次硬切与实施顺序”采用一套当前合同。页面方案保持 Market data、Financial data、Industry data、Strategy Benchmark 四块；新增的两个后端家族归入现有行情/财务类别，分别承载 22 / 204 个目标字段，不把供应商接口数映射为页面卡片数。

## 事实核查门槛，不让用户猜来源定义

- 源单位：gross_profit 的金额尺度、equity_yoy 与换手率的缩放尚需逐列核实。已确认目标表示，不代表来源尺度已获证。
- 源期间：impai_ttm 的名字不能证明其数值是 TTM，官方当前说明没有确立这一点。
- 披露频率：最新整行某列为空会得到缺失；哪些 fina_indicator 列只在年度或其他固定期间披露尚未由现有年报单样本证明。先核查，再固定逐字段报告选择。
- 修订顺序：fina_indicator 的 update_flag 不具备已验证的时间或优先级合同；不复用三表的 update_flag=1 排序推断。
- 来源截断和全历史覆盖：遵守 [来源设计核查](223-source-design-review.md)，工程资格验证与实际覆盖统计是实施门槛。

## 当前文档

- [设计](spec.md)
- [最新版 226 字段清单](../../docs/research/dsl-field-catalog-226-2026-09-12.md)
- [32 项三表扩展定义](statement-extension-32.json)
- [核心 TTM 三项](core-flow-ttm-3.json)
- [已撤回的 Q4 期间明细展示提案](period-evidence-presentation.md)

## 会话规则

本记录来自用户指定的 grill-with-docs，已明确的决定写入词汇和必要 ADR。随后按用户指定的 to-spec 合成为正式规格，后续实施以规格和 226 字段附件为准，不重新启动已经结束的产品访谈。本轮只整理并发布本地规格，未执行应用实现或线上切换。
