# 信号评估、策略回测与前向追踪

Status: needs-triage

> 本文保留设计过程及代码接缝。正式需求、收敛后的首版范围和可实施状态以 [spec.md](spec.md) 为准；本文件的阶段状态不表示仍需方向确认。

2026-09-12 更新。用户已同意按三种能力的方向修改，并在 grill-with-docs 中确认信号评估与回测分开运行、末日正常执行与零波动候选处理。当前 checkout `2daf193` 的代码核对与修订见 [本轮审查](three-capabilities-review.md)，全部已答决定见 [决策树](decision-frontier.md)。本文记录设计，未实现、测试、提交或发布产品功能。

本轮明确需要信号评估、策略回测、前向追踪，以及持仓、模拟订单、模拟成交和新增决策结果。非等权已纳入评分策略；直接目标权重和有状态 `trade_when` 仍是另外的表达能力，不因引用讨论自动纳入本次交付。Q1 已确认分开运行：Factor Evaluation 独立提交，Strategy Backtest 与 DailyTrack 不隐式附带信号评价。

用户最终选择 [临时每日持仓](temporary-holdings-design.md)：正常运行生成逐日实际持仓，按实际读取续期、到期清理；需要时用当前数据另行重跑，接受新旧结果不同。每日账户汇总与必要终端/发布状态继续保留，诊断期限不影响原 Result 或续算。本稿采用完成后 7 天、读取后续期 7 天的建议默认值，未将期限数字视为用户指定。

## 1. 产品结构与现有基础

保留两种 ResearchRun 与一个 DailyTrack，形成三个独立入口。信号评估不是策略回测的准入门槛；DailyTrack 从成功回测的已发布状态开始。

```text
网页 / MCP
  ├─ 信号评估 → ResearchRun(factor_evaluation) → 信号评价 Result
  ├─ 策略回测 → ResearchRun(strategy_backtest) → 策略 Result
  │                                               │
  └─ 前向追踪 ← 从该 Result 创建 DailyTrack ←───────┘
                  └─ 手动 Refresh → Tracking Advance → 新发布状态

三者共用：数据依赖解析、表达式 Module、结果发布与查询约束
回测与追踪共用：策略目标、执行与账户计算
```

三项能力按输入和结果区分，不拆成三个独立回测引擎，不要求新增 Experiment 实体、通用 DAG、Comparison 编排或 Temporal。Agent 可以多次调用这些能力组织自己的研究。

### 分开运行的合同

| 能力 | 实际执行与结果 | 续算边界 |
|---|---|---|
| Factor Evaluation | Signal 与未来标签配对，输出 IC、Rank IC、分组收益、覆盖和时段统计；不模拟策略账户 | 保留该评价任务需要的统计与计算进度 |
| Strategy Backtest | 计算必要 Signal、Selection、Weighting、Exposure，输出账户和交易结果；不生成 Factor 标签或评价产物 | 保留策略、账户、待执行目标及必要信号计算状态 |
| DailyTrack | 从成功策略 Result 延续同一策略与账户，输出新增账户和交易结果 | 不携带隐式 Factor 摘要、标签成熟或滚动评价状态 |

两类 ResearchRun 各有自己的生命周期与 Result，不能用隐藏页面代替执行分离；首版不新增 `include_factor` 或复合运行形态。保持 Signal/Alpha 的计算能力和时间口径，去除的是策略路径对未来标签评价的强制依赖。普通 Run、Batch 子 Run 和 Track 的类型、执行计划、Chunk 完成条件及续算状态都遵循此边界。

当前代码事实：

| 位置 | 已有能力 | 本轮需要深化的部分 |
|---|---|---|
| [ResearchRun models](../../apps/core/src/thesistrace/research_run/models.py) | `factor_evaluation` / `strategy_backtest` 判别类型、冻结输入、独立生命周期 | 明确信号评价配置、StrategySpec、SimulationSpec；解除策略结果对 Factor 的强制依赖 |
| [Factor Kernel](../../apps/core/src/thesistrace/research_kernel/factor.py) | 1/5/20 Session 的 IC、Rank IC、五组收益、样本统计 | 保留每日评价统计并支持按时段汇总，清楚返回标签和统计口径 |
| [Strategy Kernel](../../apps/core/src/thesistrace/research_kernel/strategy.py) | 顺序模拟、订单/成交、每日持仓变化的内部记录 | 实际本金、策略目标输入、共享续算、可发布的明细 Schema |
| [Result Schema](../../apps/core/src/thesistrace/research_run/result_schema.py) | Factor 摘要、Strategy 摘要和每日账户观察 | 期末/已发布状态及事件的永久结果合同，独立临时每日持仓的查询与到期状态 |
| [DailyTrack calculation](../../apps/core/src/thesistrace/daily_track/calculation.py) | 从已有状态推进、Checkpoint、续算 | 与扩展后的策略、模拟配置及明细发布保持一致 |
| [MCP registry](../../apps/core/src/thesistrace/research_agent/registry.py) | 发现、诊断、提交、状态、分区结果、Track 创建/刷新 | 复用已有工具名和资源身份，扩展类型与结果分区 |

引用讨论中的 `factor_evaluate` 工具和 Temporal Pipeline 不是当前仓库的已实现契约。当前原生 MCP 提交入口为 `submit_research_run`；执行使用已有 PostgreSQL 队列和独立 Worker 池，见 [Core 架构](../../docs/architecture/core.md)。

## 2. 输入分工

以下类型名和嵌套字段是建议形态，不是已发布 Schema。

| 配置 | 内容 | 使用者 |
|---|---|---|
| ResearchScope | 日期、现有 Liquidity Universe；准入时解析的 Research Sessions 与 Data Generation | 信号评估、策略回测；追踪继承范围规则并追加日期 |
| SignalSpec | 表达式、信号方向约定、现有中性化配置 | 信号评估、使用评分选股的策略 |
| SignalEvaluationSpec | SignalSpec、未来收益定义、要返回的评价结果 | 信号评估 |
| StrategySpec | 如何选择股票、分配权重、控制 Exposure、何时发布目标 | 策略回测、前向追踪 |
| SimulationSpec | 初始本金、现有费用与成交/数量/估值模型及其版本 | 策略回测；追踪冻结继承同一模拟规则 |

SimulationSpec 首先把实际使用的模拟假设固定下来，不意味着立即允许任意券商、分钟成交或所有成本模型。仅将已实现且可用的模型及参数列入 catalog。

不为这三项能力单独创建 ExperimentSpec 或独立的策略管理生命周期。接受后的 Run 内保留规范化定义及内容身份；Track 复制或持有受其拥有的固定 Origin，不依赖可编辑草稿，也不因来源 Run 删除而失去续算输入。

## 3. 信号评估

输入只要求 SignalSpec、ResearchScope 和标签/评价配置，不要求本金、持仓数量、Weighting 或 Exposure。

首版标签沿用当前 next-open 语义：信号 Session 为 `t`，以 `t+1` 的调整后 Open 为起点，`t+1+h` 的调整后 Open 为终点，`h` 使用当前支持的 1、5、20。口径成为结果中的显式值；更多期限或价格定义必须先作为正式能力实现。

计算流程：

```text
冻结数据 → 计算 Signal → 研究资格与中性化 → Final Alpha Cross-Section
                                                 ↓
                                与每个期限的未来收益标签配对
                                                 ↓
                          每日 IC / Rank IC / 分组收益 / 覆盖统计
                                                 ↓
                                 全期及按年/月等时段汇总
```

Signal 的股票范围与 Factor 标签可用样本分别记录。首版沿用现有研究结束边界：`t+1+h` 超过 Research Period 末日的标签记为 `right_censored_by_research_period_end`，即使更晚历史行情已完整存在，也不自动向所选区间外读取。返回各期限实际可评价信号区间及尾部未评价数量，不补成零，也不把它当成数据异常。Warm-up 不计入研究绩效，未来标签不作为策略输入。

月/年稳定性按信号日期对同一次完整研究的每日统计分组，对有效每日 IC 等日权汇总；分组本身不在每月边界重新截断标签。每日横截面相关性的时段汇总不能变成把全部股票和日期混起来算一次相关性。保留原有并列分数的组划分口径，允许合法空组，不为凑齐五组强制拆散同分股票。

结果至少包括：各期限摘要、逐日相关性、五组收益与组样本数、有效/排除样本数、可计算日期数、数据和定义身份。稳定性首先表示各时段这些统计的变化，不新增一个含义模糊的“稳定性得分”或通过门槛。

五组收益是信号分组的 Forward Return，不是扣除交易成本后的可执行组合回测。结果界面和 MCP 都应保持这一区别。

## 4. 策略回测

输入是 StrategySpec、SimulationSpec 与 ResearchScope，可以直接提交；无需先提交 Factor Evaluation，也不以 IC 达标作为运行条件。回测独立输出账户与交易结果，不计算或返回 Factor Evaluation。需要评价同一 Signal 时，另行提交信号评估 Run；它的完成、标签边界或统计是否有效不决定策略回测能否完成。

推荐先把已经讨论的评分策略表示为：

```text
StrategySpec(kind = signal_allocation)
  signal: SignalSpec
  selection: holdings_count + selection_every_sessions
  weighting: 等权 / 排名加权 / 波动率倒数加权
  exposure: 每个已完成 Session 的账户目标仓位表达式
```

Weighting 已纳入本轮方向，等权为默认值。规则在定期选股时生成和保留相对目标权重。对非空的最终入选集合，权重非负且合计为 1；账户目标股票权重在形成配置目标时由 Exposure 与这些相对权重共同决定。零有效候选时 Target Selection 为空，股票配置目标为零，不修改 Exposure 表达式本身的返回值。

首版计算口径：

- 等权：K 个最终入选者各为 `1/K`。
- 排名加权：在最终入选集合内，按 Final Alpha Value 降序排列，以 `K+1-r` 为原始权重后归一化；并列者共享其占据名次的平均权重。Top-N 边界并列仍沿用股票身份的确定性排序。不能直接把全 Universe 的 `rank(signal)` 百分位当成该规则。
- 波动率倒数加权：使用截至选股日收盘的调整后 Close 单日收益，窗口参数默认 20 个 Research Sessions；沿用现有 `ts_std` 的总体标准差约定，以 `1/σ` 在最终入选集合中归一化。窗口及其前置收益观测加入 Weighting 的真实数据依赖，不只解析 Signal 的窗口。
- Q3 已确认：零波动候选不适用本次配权，按信号名次向后顺延；候选不足时用剩余有效者归一化，全部无有效候选时目标空仓。不暗加 epsilon，不转为等权，不将合法零波动报成历史数据缺失或整次回测失败。

例如账户权益 10 万元、Exposure 0.7、三只股票相对权重 0.5/0.3/0.2，对应目标金额 3.5/2.1/1.4 万元。实际现金和持仓由数量约束、费用与成交结果决定。

沿用已确定的评分策略规则：选股按周期更新；Exposure 每日计算并在下一 Open 尝试执行；无新目标时不因价格漂移交易；非选股日减仓按实际持仓比例，增仓向保留的目标名单/权重补足；同日双触发合并；当次受阻订单不逐日重试。新增 Weighting 不自动改变这些规则。

### 直接目标权重与 trade_when 的位置

为了避免外层回测永久要求 Alpha/Top-N，建议 StrategySpec 的类型设计容纳独立的 `target_weights` 形态：其表达式直接给出每只股票相对于账户的目标权重。这是策略表达扩展建议，不是本轮三个能力接口成立的前置条件；只在实现完成后对外宣告支持。

- `signal_allocation` 使用相对权重与 Exposure；`target_weights` 已提供最终账户权重，不能再强制 Top-N、等权或重复乘 Exposure。
- 在当前不加杠杆、多头范围下，直接目标权重非负、合计不超过 1；剩余为现金。合计 0.4 不应自动拉满至 1。
- 两种输入都转成明确的目标事件：不更新，或设置一个完整的新目标。设置全零目标可以表达清仓；未列入完整目标的实际持仓目标为零，执行约束仍可能使其保留。
- 不更新不等于清仓，也不等于每天恢复旧权重。下一步订单只能从实际持仓与新目标的差额生成。
- `trade_when` 属于是否更新/退出及状态语义，不能从“提供策略回测能力”自动推导出来。先前不加入有状态 DSL 的决定仍须与这项扩展分开；任何后续引入都必须在回测与 Track 使用同一状态转换定义。

这种分工参考 QuantConnect 将组合目标构建与执行分开：组合构建产生目标，Execution 消费目标进行交易。[Portfolio Construction](https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/portfolio-construction/key-concepts)、[Execution](https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/execution/key-concepts)。这里保留 ThesisTrace 的日频和账户约定，不照搬其默认触发行为。

## 5. 前向追踪

前向追踪继续使用 DailyTrack。创建时选择一个成功 Strategy Backtest 的已发布 Result，继承其固定 StrategySpec、SimulationSpec、数据范围规则、实际持仓/现金、选股相位、保留目标及必要续算状态。

“已发布状态”是产品已经原子提交的账户与进度，不增加人工审批或新 Publish 按钮。初始本金继续用于原账户收益基线，不在每次 Refresh 重置资金或重新从现金建仓。

一次手动 Refresh 接受一个固定的新增 Session 范围与 Data Generation，交由现有 Tracking Worker 运行。完成后一起发布新增结果、Checkpoint 与进度；失败的临时计算不改变此前发布的账户或原回测 Result。没有新 Session 时沿用现有状态反馈，不把原回测标记成失败。

Q2 已确认新的终点合同：最后一个纳入区间的 Session 也正常执行此前已形成、应在当日 Open 执行的交易，再记录费用及 post-trade Open NAV；末日不强平。最后收盘形成的下一 Open 决定作为待执行状态保留。Track 从这个完整状态继续，仅发布更晚 Session，不重算或覆盖旧终点。首次研究 Open 仍保留原来的全现金起点，不把 Warm-up 的决定变成首日持仓。

该规则改变了当前代码的 `terminal_valuation` 免交易行为，也取代后续 Advance 可以替换上次边界观察的行为。不能在维持旧终点算法的同时声称严格追加及跨任意分段等价；需要随计算合同变更一起实现。

权威续算状态必须保存已经决定的目标值：最近 Target Selection、相对权重、有效 Exposure、待执行的下一 Open 目标、决策日期和其数据身份。只保存 `signal_session` 再从新 Generation 重算过去决定不充分；临时缓存丢失不能改变已完成决定。未来 Session 的新决定仍可使用该次 Advance 固定的新数据。

策略版本在原 Track 内保持固定。修改策略后使用新回测和新的 Track，不把修改前后的表现混成同一策略的前向证据。历史数据修订不悄悄改写已经发布的追踪历史。

输出包括新增 Session 范围、最新实际持仓/现金、净值和收益、目标更新、模拟订单/成交、真实发生的受阻/估值信息，以及使用的数据身份。累计表现保留原 Tracking Origin 的基线；展示追踪区间表现时另外明确区间起点。

这种追踪是已发布日线数据上的连续模拟，不是券商实盘或实时 Paper Trading。DailyTrack 不维护信号未来标签或 Factor 评价结果；若要研究新增时期的信号质量，另行提交 Factor Evaluation，按其所选研究区间和标签边界计算。

## 6. 共享计算与发布

保持现有 Module 所有权，深化已有 Interface：

| Module | 负责的变化 | 不承担的职责 |
|---|---|---|
| Data / Research Authoring / Alpha Language | 输入作用域、可用能力、类型、窗口与依赖编译 | 从页面推断策略含义 |
| ResearchRun | 按 Research Kind 接受并冻结输入、异步生命周期、发布该类完整 Result | 强制两类任务都执行 Factor 或自行实现第二套交易循环 |
| Research Kernel 的 Factor 计算 | 数值信号与未来标签的评价 | 操作账户或给策略提供未来标签 |
| Research Kernel 的 Strategy 计算 | 从策略定义和实际状态产生目标、订单、模拟成交及新账户状态 | 管理 MCP 会话或研究编排 |
| DailyTrack | 固定 Origin、显式 Advance、当前已发布策略账户状态 | 隐式维护 Factor 评价、使用简化版成交或单独复制策略规则 |
| 现有 Publication 与 Result 查询 | 验证、发布、读取各类产物 | 把未完成 Attempt 当成成功结果 |

内部运行契约可概括为：`advance(strategy, simulation_rules, visible_data, prior_state, sessions)` 返回新的状态与本段产物。历史回测以初始现金建立状态，Track 使用前一已发布状态；同一套目标、成交与账户逻辑处理两者。具体批量计算、向量化和续算缓存保留在 Implementation 内。

所有计算路径继续保证收盘可见数据到下一 Open 的时间对齐，沿用当前 Open 估值结果口径。不能在新增前端图表时把已有 Open NAV 标成 Close NAV。当前合成账户的 Execution Share Quantity、Adjusted Holding Units、Raw Market Price 与 Research Settlement 在产物中分清，不能包装成真实券商交割单。

## 7. 结果明细与存储范围

每日持仓明细用于事后检查实际仓位、持仓结构和交易行为。按用户最终选择，正常策略运行直接保存它们，作为有闲置期限的诊断产物；无需先重算才能首次查看，也不永久累积全部历史。完整规则见 [临时每日持仓设计](temporary-holdings-design.md)。

| 产物 | 保存粒度 | 主要查询 |
|---|---|---|
| signal_summary / signal_daily | 每期限摘要、每日统计与样本数 | 期限、信号日期、统计区间 |
| strategy_summary / observations | 摘要与每日账户数值 | 日期范围 |
| positions | 回测期末，或指定 Track 发布版本终点的实际持仓，复用其完整账户状态 | 所属 Result/发布版本、股票；返回明确的 as-of Session |
| holding_history（临时诊断） | 每个已完成 Session 实际持有股票的数量、当时估值和权重，另有空仓日覆盖信息 | 有效期内按日期、股票分页；显示来源执行、覆盖范围和 expires_at |
| target_events | 发生目标更新时的目标及触发类别 | 决策日期、执行日期、股票 |
| orders / fills | 实际模拟的逻辑订单及成交；保留必要父子关联 | 日期、股票、订单身份、状态 |
| execution_events | 实际发生的受阻、退市处理、估值等业务事件 | 日期、股票、事件类别 |
| provenance / terminal_state | 固定输入、版本和终端续算状态 | 按所属 Run / Track 发布版本读取 |

`signal_summary / signal_daily` 属于 Factor Evaluation；策略账户、持仓和交易产物属于 Strategy Backtest / DailyTrack。`holding_history` 与永久 Result/Checkpoint 的必需分区分开，拥有独立到期状态；其删除不破坏原结果完整性。各类 Result 只声明本能力的产物及可用性，不填充另一能力的空占位。

每日净值、收益、费用、实际仓位比例等账户汇总和 `positions` 终点持仓保持原有结果生命周期；Track 每次成功 Advance 的完整 Checkpoint 也继续保留。临时 `holding_history` 按 Run、Batch 子 Run、Track 每个 Advance 分别计时，初始从成功发布后保留 7 天，实际读取未过期明细后续期 7 天；摘要、列表和状态轮询不续期，Track 新 Refresh 不延长旧段期限。

到期后返回明确的 `expired`，后台清理临时产物；不以空数组冒充空仓。后续排障使用原策略/模拟参数和研究区间，在当前可用数据及当前应用合同下另建普通回测，不要求保存旧 Generation、历史引擎或原样恢复旧持仓。新 Run 内仍固定输入，产生的明细和指标标明新来源，不能覆盖原 Run 或原 Track；新旧差异不构成重跑失败。首版不增加事件还原或精确重放系统。

价格、权重、数量、费用和收益各自声明单位。模拟订单和成交必须能关联到目标事件并对上实际现金/持仓变化；一次订单受阻可以成为正常结果的一部分，不等同于整次计算错误。这里只记录可验证的触发事实，不新增自然语言逐股解释或每个算子求值日志。

必须补齐的产物合同：

- 逻辑事件身份独立于 Chunk、Attempt、Retry 和数组下标；由固定决策、执行 Session、股票、方向及必要的确定性序号形成，子订单及成交关联其父事件。资源身份负责所属关系，逻辑事件键用于关联及等价验证。
- Fill 保留执行股数、Raw Open、Raw Notional 和费用，也要给出实际 Research Settlement、现金增减和 Adjusted Holding Units 增减。当前合成账户卖出现金不总等于原始股数乘原始价格，直接公开内部 Fill 的已有字段不足以承诺现金对账。
- 目标与交易事件进入主 Chunk 计算与发布链；期末/已发布持仓复用终端状态。临时每日持仓从同一执行核心有界收集、分段写入独立诊断产物，不先在内存累计整段历史；Retry 不重复发布或累计成交。
- 查询区分“已保存且零条记录”“旧结果未保存”和“临时明细已过期”，不能以空数组替代后两种状态，也不在读取过期明细时隐式提交回测。

生命周期与产物 manifest 继续由 PostgreSQL 管理，较大的不可变事件、统计及临时持仓分区使用现有 RustFS 和压缩列式文件能力。Track 只追加本段产物，不在每次 Refresh 复制全部历史。临时数据到期后先撤销自己的引用，再由现有 Publication 引用检查清理无其他引用的对象；不能按共享桶对象年龄粗暴删除。读取续期与清理须协调，已有永久 Result、Checkpoint 和底层行情数据不因这项期限规则被删除。

默认工具读取摘要，各 section 只接受其支持的过滤条件。`positions` 查终点状态，临时 `holding_history` 有效期内按日期/股票查询；cursor 绑定实际来源执行与产物，不能在过期后切换成另一次重跑。沿用 Researcher 所有权检查，不直接暴露对象存储地址作为授权。

存储量核算区分永久结果、临时持仓与事件数量。例如按每年 250 个交易日、每天持有 100 只估算，10 年每日持仓约为 25 万条；闲置期限限制其历史累积，但不消除本次写入和磁盘峰值。未读取部分的稳定占用主要取决于保留窗口内的回测产量，另计被持续读取的产物和清理滞后；实际字节数、压缩率及高换手事件量需测量。

## 8. MCP 与 HTTP 契约

三种产品能力不等于只允许三个 Tool。保留现有资源式接口，网页和原生 MCP 调用同一 Core Interface。

| 行为 | 推荐契约 | 与当前关系 |
|---|---|---|
| 发现能力 | `get_research_context` + `get_alpha_catalog` | 扩展输出作用域、可用 Strategy 形态、模型和参数约束；未实现能力不列为支持 |
| 校验整份配置 | `diagnose_research_spec(spec)` | 建议新增；与编辑器逐表达式诊断职责不同，复用准入编译与检查 |
| 运行信号评估 | `submit_research_run(research_kind="factor_evaluation", ...)` | 保留工具和 kind，使用信号评价输入 |
| 运行回测 | `submit_research_run(research_kind="strategy_backtest", ...)` | 保留工具和 kind，接受 StrategySpec / SimulationSpec |
| 查看进度 | `get_research_run(run_id)` | 沿用异步状态和轮询建议 |
| 查询结果 | `get_research_run_result(run_id, section, filters, cursor)` | 扩展有类型的结果分区与过滤参数 |
| 开始追踪 | `start_daily_track(origin_run_id, request_id)` | 从成功策略 Result 开始，参数名以当前 Schema 对齐 |
| 推进追踪 | `refresh_daily_track(track_id, request_id)` | 沿用显式接受一次 Advance |
| 查询追踪 | `get_daily_track` / `get_daily_track_result` | 状态与结果分开；明细同样分页并固定发布版本 |

上表嵌套输入和过滤参数是目标设计，不可当作现在能直接执行的请求。现有取消、停止与 Retry 工具继续按原权限和生命周期工作。

配置诊断不占有 Data Generation，也不保证稍后提交一定被接受；正式提交仍原子解析并冻结输入。提交返回 accepted/rejected、资源身份和规范化定义，accepted 不是 completed。所有改变状态的请求保留稳定 `request_id`；重连不能重复提交，Retry 不改变原先冻结的数据或策略定义。过期持仓的重新生成属于新的 Run，采用当前数据，不是原 Attempt 的 Retry。

普通 Run、Batch 和 Track 的共享计算只在输入及计算合同相同的情况下复用。Batch 继续复用符合条件的 Data/Alpha；Factor 仅为实际 Factor Evaluation 请求计算并在符合条件时共享。Strategy 子 Run 和 Track 不携带未请求的 Factor 执行与续算状态；不因为加了一层调用包装就宣称不同请求自动消除了重复计算。

## 9. 前端映射

沿用现有导航和 [DESIGN.md](../../DESIGN.md) 的工作台。Research 选择“信号评估”或“策略回测”；Daily Tracks 呈现“前向追踪”。

- 信号评估：Signal、研究范围、当前支持的未来收益期限与口径；结果展示相关性、分组收益、覆盖和按时段变化。
- 策略回测：Strategy 区的 Signal/Selection/Weighting/Exposure 与 Simulation 区的本金/模拟规则；直接权重形态只有实现并被 catalog 宣告后才出现。
- 回测结果：绩效、期末实际持仓、目标与交易明细、运行条件；临时每日持仓展示有效期和日期查询，过期时可显式重新回测；提供从成功结果开始追踪的入口。
- 前向追踪：固定来源、最新进度、手动 Refresh、绩效、当前发布状态的实际持仓和本次新增目标/模拟交易；新增段每日持仓按各自有效期查询。展示时明确持仓截至日期、决策与尝试执行日期。

选择能力时隐藏无关输入；切换结果页不能用当前草稿替换已冻结配置。明细分页与加载状态使用后端结果合同，不把整个矩阵加载到浏览器再过滤。净值曲线继续保留每日数据；查看相应每日持仓时实际读取临时分区并续期，过期时显示状态而不自动重算。重跑结果跳转到新 Run，明确其使用当前数据。

## 10. 实施切片与验收

每个切片都有完整的 Core、HTTP/MCP、前端和必要的数据迁移；不先暴露尚不可执行的 schema 选项。

| 顺序 | 可独立验收的交付 |
|---|---|
| 1 | 显式规范化 Strategy/Simulation 输入；真实本金贯穿 Run/Batch/Track；未改变的等权规则在相同输入下等价，末日交易单独验证已接受的语义变更 |
| 2 | 共享表达式与目标生成支持已确认的每日 Exposure、定期选股；Weighting 按本轮设计收敛后接入同一流程 |
| 3 | 信号评估独立提交，返回标签合同、每日统计和时段汇总；Run/Batch/Track 的策略执行、结果与续算解除 Factor 依赖，保留必要 Signal 计算 |
| 4 | 查询终端持仓、发布事件与独立临时每日持仓；贯通网页/MCP 的读取续期、到期状态、安全清理及当前数据下的新 Run 重跑 |
| 5 | 完成不同本金、目标变化、受阻、分段续算、并发 Refresh 与 Retry 的必要验证；直接目标权重如纳入交付则作为同一运行核心的独立切片 |

核心验收：

1. Signal Evaluation 的指标能由小样本独立核算；分组 Forward Return 不混入交易成本，标签不能泄漏给策略。
2. 同一 Signal 搭配不同 Weighting/Exposure 时，差异来自目标及真实执行，期末现金、持仓和费用能从期初状态、成交结算及其他实际调整独立对账，无需永久保存逐日持仓快照。
3. 在相同数据、策略、模拟合同和 Origin 下，全区间计算与分段推进的账户、目标、逻辑订单/成交和终端状态一致；验证切分点正好存在交易与费用的情形，已发布追踪历史不会被续算或后续更正覆写。使用不同历史修订版本重新跑全区间不属于相同输入等价。
4. 成交与账户发布不因重试重复；读取同一发布版本的分页明细稳定。受阻订单与基础设施失败使用不同的结果/生命周期含义。
5. 网页与 MCP 接受同一配置并读到同一组结果；无关策略字段不会混入 Signal Evaluation。同一信号可以分别提交两类 Run；Strategy Run/Batch/Track 不计算未来标签、不要求 Factor 摘要或成熟状态、不返回 Factor 分区，也不影响独立 Factor Run 的原有每日评价口径。
6. 临时持仓收集、读取和到期清理不改变永久指标、终端状态或续算；验证实际读取续期、轮询不续期、并发清理和引用保护。旧数据版本缺失时仍可按当前数据重跑，允许新旧指标不同，并保持来源与结果分离。

验证入口依照 [仓库约定](../../AGENTS.md#testing)，使用受影响测试与真实依赖，不为文档修改运行整套产品测试。存量 Result 保留原数值和计算来源，迁移后的当前查询合同须说明未记录的明细；不从摘要伪造历史交易。

存量策略 Result 曾附带的 Factor 数值也属于应保留的历史证据。显式迁移须保留这些值及原结果来源，并在当前查询合同中明确其历史归属；不能为了新任务分开运行而静默删除、改算或把它们冒充一个独立执行过的 Factor Run。新策略执行与 Track 续算不再依赖这些历史评价状态。

旧终点合同与新终点合同不同，新合同重算不能说成旧回测精确重放。用户已允许过期后的持仓排障直接使用当前数据重新回测，不要求找到旧数据或旧计算合同；应用继续使用单一当前引擎。新的 Result 保留与原研究的来源关系及实际差异，不改写原研究。

存量 Track 的升级需单独验证状态语义：不可通过改版本号、悄悄补做旧末日交易或改写原净值使旧 Checkpoint 冒充新合同的完整状态。无损可迁移的状态采用显式迁移；不能保持含义的旧执行状态按当前合同约束停止准入，保留可读历史，并通过新回测/新 Track 建立当前合同起点。具体迁移要限定起止版本、备份、记录结果并验证失败回滚，禁止自动清库或运行时多版本兼容。

## 11. 与已确认范围和 ADR 的关系

保留原设计的日频时点、手动 Refresh、固定 Origin、实际本金、Universe/申万一级共同指标范围及受阻规则。

- 已更新 [ADR-0040](../../docs/adr/0040-use-one-long-only-top-n-equal-weight-strategy.md) 和 [ADR-0042](../../docs/adr/0042-use-only-scheduled-alpha-snapshots-for-periodic-full-rebalancing.md)，记录评分策略可配置 Portfolio Weighting，保留已接受的选股/Exposure 时点；直接目标权重仍是独立扩展。
- 已更新 [ADR-0099](../../docs/adr/0099-make-one-immutable-result-bundle-the-research-run-truth.md)，区分完整不可变 Result 与按读取续期的临时每日持仓；到期清理后可用当前数据重跑，不承诺原样复现。
- 已按 Q2 更新 [ADR-0055](../../docs/adr/0055-record-strategy-nav-after-each-open-execution-cycle.md) 与 [ADR-0105](../../docs/adr/0105-publish-one-immutable-tracking-checkpoint-per-advance.md)，记录末日正常执行、已完成边界不替换和已决定目标的续算。
- 已按 Q1 更新 [ADR-0214](../../docs/adr/0214-select-factor-evaluation-or-strategy-backtest-within-researchrun.md)，明确两类 ResearchRun 分开运行、策略与 Track 无隐式 Factor 依赖，Batch 遵循相同的按类型执行与结果合同。
- 同步 [ADR-0216](../../docs/adr/0216-share-bounded-batch-calculation-and-recover-complete-tasks.md)：Batch 按请求类型共享必要计算，Strategy Sweep 不再默认计算 Factor；保留完整任务恢复，不增加 Chunk/Session 级持久恢复。
- 保留 [ADR-0104](../../docs/adr/0104-continue-dailytrack-from-one-fixed-origin.md)、[ADR-0234](../../docs/adr/0234-require-explicit-dailytrack-refresh.md) 和 [ADR-0222](../../docs/adr/0222-keep-research-agent-execution-stateless-and-resource-addressed.md) 的固定 Origin、显式刷新、资源身份和幂等原则。

CONTEXT 与 ADR 记录已接受的领域含义和决定；它们不证明代码实现已完成。本轮 Q1–Q3 全部已答，后续按确定的规则细化实施与验收，不重复请求方向确认。

## Comments

- 2026-09-11：用户从参考讨论中选择信号评估、策略回测、前向追踪三项能力。核对完整引用后，纠正其中关于当前 `factor_evaluate`、Temporal 的假设；以现有 ResearchRun、DailyTrack、Kernel 与 MCP 为设计落点。
- 2026-09-12：用户同意该方向并要求 grill-with-docs。两项独立代码审查发现真实终点/续算矛盾以及产物、配权和标签口径缺口；用户确认 Q2 末日正常交易与 Q3 零波动排除顺延，随后回复“分开运行”确认 Q1。三项决定已同步到执行、结果、续算、前端与 ADR 设计。
- 2026-09-12：用户以 100 只股票、10 年、Agent 批量回测质疑每日持仓的必要性与存储成本。设计撤回逐日逐股持仓的必存要求，保留已有汇总/净值、必要终端与发布状态以及真实目标/交易事件；首版不承诺任意日期持仓查询或新增历史还原系统。仅修改设计，不删除已有数据。
- 2026-09-12：用户进一步明确保留有期限的每日持仓，未读取/未排障则到期删除，之后可直接用当前数据重跑并接受差异。此前不保存每日持仓及必须原条件重算的备选已被替代；本轮建议默认 7 天闲置期限，更新临时产物、前端/MCP、清理和来源合同，未操作实际数据。
