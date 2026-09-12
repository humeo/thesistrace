# 首版前端变化：三种能力与可配置策略

Status: needs-triage

> 正式功能范围与验收以 [spec.md](spec.md) 为准；本文保留前端设计说明，不是独立待确认事项。

2026-09-12 更新。沿用 2026-09-11 对线上 `/research` 的截图与本地前端代码核对，补入用户接受的三种能力、Weighting 与正式明细。本文是界面方案，尚未修改产品实现；行为范围以 [spec](spec.md) 和 [三种能力设计](three-capabilities-design.md) 为准。早期交互示意只展示了 Signal/Exposure，不代表已经覆盖本轮全部控件。

## Research：主要改动

保留现有左编辑区、右参数面板和主 Run 操作。Strategy Backtest 下，左侧分开显示 Signal expression 与 Exposure rule，避免将选股评分和组合仓位写进同一个编辑器；窄屏顺序排列。可选的标签切换布局仅是呈现替代方案。

- Signal expression：沿用 Alpha 编辑器，补充比较、布尔、if_else 及可用共同输入的自动补全。其结果依然是每只股票的评分。
- Exposure rule：新增组合仓位编辑区。固定仓位百分比是常量表达式的便捷输入，表达式模式直接编辑 0 到 1 的每日仓位结果；两者只对应一份 exposure_expression，不持久化两套策略规则。无需另造一套可视化策略编排器。
- 输入目录：从后端 catalog 插入已支持的市场/行业指标，显示指标名称、作用范围及计算口径。选择参考行业只指定条件输入，不修改 Universe。示意中的变量别名只是展示样例，不能当作已经发布的 DSL 语法或字段身份。
- 两个编辑器共享 catalog，但按作用域提供补全：Signal 可用个股字段及共同指标，Exposure 只提供常量和适用的共同指标。输出分别标明“每股评分”和“账户目标仓位 0–1”，后端同时校验，不能靠前端隐藏代替合法性判断。
- 参数面板：新增 Initial capital (CNY)；Holdings count 保留；Rebalance sessions 改成 Selection interval。直接说明选股按周期更新，仓位每日计算，目标变化后下一 Open 尝试执行。
- Weighting：在选股配置旁增加等权、排名加权、波动率倒数加权选择；后者显示窗口参数。说明权重随选股更新，零波动按已选规则排除顺延。实际规则和参数来自 Core，前端不计算另一套目标权重。
- Factor Evaluation：产品入口可标为“信号评估”，显示信号、区间、Universe、中性化及当前支持的标签期限/口径；隐藏账户和选股配权控件。条件 Alpha 和共同输入仍可用于因子公式。与策略回测分别提交 Run，后端同步分开执行和结果合同。
- 提交/保存：草稿保留两种表达式及本金；语法/类型问题定位到对应编辑器。Run 的合法性及数据依赖仍由共享 Core 检查，界面不得另算一套策略或把模拟校验当成成功回测。

当前接缝：[ResearchWorkspacePage](../../apps/web/src/research/ResearchWorkspacePage.tsx)、[AlphaFormulaEditor](../../apps/web/src/research/AlphaFormulaEditor.tsx)。

## Data：使衍生输入可发现

现有 6 个行情字段、6 个财务字段及行业就绪信息继续保留。在 Research fields 附近增加可发现的 Market / Industry indicators 分组，区分“个股字段：每只股票每天一个值”与“共同指标：每天一个共享值”。

行业指标说明复用个股行情与历史行业归属，展示真实成员范围、聚合定义和可用条件；不标成新增外部原始行情，也不把 Universe 内的行业子集称为全行业。只有已实现且可用的指标进入目录。此分组可以复用已有表格/详情呈现，不新增顶级导航或数据诊断产品。

当前接缝：[DataPage](../../apps/web/src/data/DataPage.tsx) 的 ResearchFieldCatalog。

## Research Runs：展示实际采用的策略定义

沿用现有列表、绩效曲线和研究详情。在现有运行条件中增加实际生效本金、Weighting、Exposure expression，把 Rebalance 改为 Selection interval，明确引用的行业指标定义；保留原 Signal、Universe、日期等信息。信号评估结果增加每日 IC、组收益/样本统计及按信号日期的时段汇总。

按 Research Kind 展示结果：新信号评估 Run 显示评价统计，新策略回测 Run 显示账户与交易，不附带 IC 或 Factor 标签页。已保存的旧策略 Result 若含 Factor 数值，按迁移后的历史证据合同保留展示及原来源，不伪装为另一次信号评估。

这些值来自已接受 Run 的冻结定义，而非当前编辑草稿。期末持仓复用终端状态；新增临时“每日持仓”视图，按日期/股票分页读取，显示原执行与保留至时间。建议默认完成后 7 天，实际读取后续期 7 天；列表、摘要和状态轮询不续期。目标事件、模拟订单和成交按日期/股票/订单过滤。明确区分该日空仓、旧结果未记录与临时明细已过期，不能用同一个空列表替代。

过期时保留原指标和曲线，显示“每日持仓已过期，可用当前数据重新回测”，通过显式操作提交新的普通回测。新 Run 使用当前数据并关联原 Run，展示“当前数据重新回测”；不要求新旧一致，不把新明细嵌入原结果冒充原始记录，也不在打开页面时自动启动计算。完整规则见 [临时每日持仓](temporary-holdings-design.md)。

末日也执行当日应执行交易，净值继续标明 Open NAV。新旧计算合同不同的结果各自展示其运行条件，不能自动覆盖旧数字来制造同一口径的假象。

当前接缝：[ResearchRunsPage](../../apps/web/src/research-runs/ResearchRunsPage.tsx) 的 ResearchRunFacts。

## Daily Tracks：纠正周期含义

现有 Rebalance 标签/区域改为 Selection schedule，显示原策略选股周期与当前相位；旁边说明每日仓位评估可能在两个选股日之间产生下一 Open 的调整。不能把“下次选股更新”标成“账户下次可能交易”。

追踪来源区域显示继承的本金、Signal、Weighting 和 Exposure 定义；这些是只读来源，不增加在既有 Track 内改策略的入口。Refresh 仍由用户手动点击，按来源策略续算，不更新 Factor 或未来标签评价。当前持仓来自永久发布状态；每日持仓按新增段各自的临时有效期读取，新的 Refresh 不给旧段续期。目标/交易区域展示本次新增事件并标示决策与执行日期；分页固定实际来源执行，新增 Advance 不重画已完成净值边界。过期历史排障可另建当前数据回测，结果不会回写 Track。

当前接缝：[DailyTrackWorkspace](../../apps/web/src/daily-tracks/DailyTrackWorkspace.tsx)、[DailyTrackObservationView](../../apps/web/src/daily-tracks/DailyTrackObservationView.tsx)。

## Agent 与网页一致

Agent 经 MCP 提交的同一 StrategySpec，在 Research Runs / Daily Tracks 中呈现相同冻结配置。MCP 连接页不需要增加策略表单；可发现能力来自共享 catalog 和工具契约，而不是依赖 Agent 操作网页。

## 界面验收重点

使用仓库 [DESIGN.md](../../DESIGN.md) 的深色工作台、现有导航及控件。验证 Strategy/Factor 分别提交与按类型展示结果、配权选择与窗口、固定/表达式仓位、草稿保存、编辑器错误定位、本金与选股周期、Run/Track 冻结定义和事件分页；另验证每日持仓的读取续期、状态轮询不续期、空仓/未记录/过期区分及新 Run 重跑来源。Refresh 前后已完成净值日期不变，临时持仓过期不影响正常续算。新依赖和额度是否可运行由后端决定；不在示意中发起实际研究。
