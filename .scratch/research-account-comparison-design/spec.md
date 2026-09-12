# Agent Quant Research：信号评估、策略回测与前向追踪

Status: ready-for-agent

2026-09-12。代码核对基线：`main@2daf193`。本规格由整轮已接受决定合成，替代同目录早期 Comparison、持仓永久保留及按原数据精确重跑的方案。`ready-for-agent` 表示需求和验收已经充分，产品尚未实现、测试、提交或部署。

## 当前执行约束

2026-09-12 最新执行约束：用户明确当前为开发阶段。本轮只实现单一当前合同，直接修改调用方与产物定义，不新增兼容分支、字段别名、旧合同读取适配、vXX 升级或版本迁移。先前所有存量转换、迁移备份/回滚/重复升级验收均撤回；其余产品功能和失败恢复验收保持。只操作新 worktree 与隔离测试资源，不删除或重置现有 dev/线上数据。严格按 01–14 串行：每票计划 → 实现 → 验证 → Standards 审查 → Spec 审查 → 修复复审 → tracker 更新 → 独立提交。

以下早期规格中 User Story 11、Implementation Decisions 12 及对应迁移验收已由本节替代；历史 Comments 保留决定来由。

## Problem Statement

Researcher 希望让 Research Agent 分别研究信号是否有效、完整策略在实际本金约束下如何表现，以及固定策略在后续数据上是否继续有效。当前已有两种 Research Kind 和 DailyTrack，但策略执行、Result 与续算仍强制依赖 Factor Evaluation；策略主要受固定本金、等权和单一调仓周期限制。仅改表单或缩放收益率，不能回答“10 万元实际可以买多少、留多少现金、换一种配权和市场条件后会怎样”。

Agent 还需要查看实际持仓及交易以解释结果。将每天每只股票的持仓永久保存，会随批量研究持续积累；完全不保存又妨碍近期排障。Researcher 已接受：正常回测生成每日持仓，闲置后删除；以后需要时用当前数据重新回测，允许与原结果不同。

当前账户终点也与新需求不同：最后一天只估值、不执行到期交易，后续追踪可能重算并替换旧边界。要提供稳定的前向追踪，必须一起修改目标、交易、终点与发布状态，不能只增加结果页面。

## Solution

提供三个独立、可由网页及原生 MCP 调用的能力，复用现有 Core Modules、Worker 和发布体系。

| 能力 | 输入 | 产出 |
| --- | --- | --- |
| 信号评估：Factor Evaluation | Signal、Research Period、Liquidity Universe、中性化、现有未来收益期限 | IC、Rank IC、五组收益、覆盖和按信号日期汇总的时段统计 |
| 策略回测：Strategy Backtest | StrategySpec、Simulation Conditions、Research Period、Liquidity Universe | 绩效、每日账户观察、终端持仓、目标与模拟交易，以及有期限的每日持仓 |
| 前向追踪：DailyTrack | 成功策略 Result 的固定 Tracking Origin、已发布账户、手动 Refresh 接受的新数据范围 | 新增账户观察、目标与模拟交易、当前发布持仓，以及新增段的临时每日持仓 |

策略搜索空间扩展为 Signal、持股数、Selection Interval、Portfolio Weighting、每日 Target Exposure 和 Initial Cash。首版配权支持等权、入选集合内排名加权、波动率倒数加权；Exposure 控制账户整体股票配置，与股票间相对权重分开。选股仍使用现有 Liquidity Universe。

成功结果的指标、净值、交易证据和必要续算状态继续保留。每日持仓作为独立临时诊断产物，默认成功发布后 7 天未读取过期，实际读取明细后续期 7 天；过期时原结果仍可查看、Track 仍可推进。重新生成明细创建使用当前数据的新 Run，明确关联原研究。

## User Stories

1. As a Researcher, I want to submit Factor Evaluation and Strategy Backtest independently, so that I can choose evidence appropriate to my research question.
2. As a Researcher, I want Initial Cash to affect quantities, costs and cash constraints, so that a CNY 100,000 backtest represents that account size.
3. As a Researcher, I want to vary selection frequency, holdings count and Portfolio Weighting, so that I can compare allocations using the same signal.
4. As a Researcher, I want daily market or industry conditions to control Target Exposure, so that allocation can change between stock selections.
5. As a Research Agent, I want a shared capability catalog and configuration diagnostics, so that I can author and submit research through MCP without operating the webpage.
6. As a Researcher, I want daily Factor evidence and explicit label boundaries, so that I can inspect signal stability without mistaking it for executable portfolio returns.
7. As a Researcher, I want a successful backtest to continue through manual DailyTrack Refresh, so that later results preserve its strategy, account and published history.
8. As a Research Agent, I want bounded queries for targets, orders, fills and actual holdings, so that I can reconcile results and investigate unexpected behavior.
9. As a Researcher, I want daily holding diagnostics to expire after inactivity, so that batch research does not retain every historical position snapshot permanently.
10. As a Researcher, I want to rerun expired diagnostics using current data, so that I can investigate again without retaining old data or replacing the original result.
11. As a Researcher, I want existing results and tracking history to survive the contract upgrade, so that new capabilities do not erase prior evidence.

## Implementation Decisions

### 1. 能力与 Module 边界

- 保留 `ResearchRun` 的 `factor_evaluation`、`strategy_backtest` 判别合同及既有 DailyTrack；不新增第三种 Research Kind、Experiment 实体或独立策略管理生命周期。
- Factor Evaluation 拥有未来标签及评价统计；Strategy Backtest 只计算必要 Signal、目标与账户，不计算标签、不返回 Factor 分区；DailyTrack 不维护 Factor 摘要或标签成熟状态。执行计划、Chunk 完成条件、Result、Checkpoint、Batch 共享与恢复均按此分离，不能只隐藏 UI。首版没有 `include_factor` 复合选项。
- Data 拥有字段、成员及可用性；表达式 Module 拥有编译、作用域、运算及依赖规划；共享 Strategy 核心拥有目标、订单、成交和账户推进；ResearchRun、Research Batch、DailyTrack 拥有各自准入、生命周期和发布；Publication 管理不可变字节及引用安全。HTTP、MCP、网页适配这些合同，不复制策略计算。
- Batch 保留现有两种 Batch Kind，不引入混合 Batch 或优化器。兼容请求真正共享 Data/Alpha；仅实际 Factor Evaluation 请求执行和共享 Factor。Strategy Sweep 每个子 Run 独立拥有本金、策略账户、Result 和临时持仓期限。恢复保留完整任务，不增加逐 Session、Chunk 或表达式节点的持久调度。

### 2. 规范化输入与能力目录

- ResearchScope 表示请求日期、Liquidity Universe 及准入时确定的 Research Sessions/Data Generation；SignalSpec 表示 Alpha Formula 和既有 Industry Neutralization。Alpha Direction 保持“分数越高，预期收益越高”，不增加自动反向或方向参数。
- StrategySpec 包含 SignalSpec、`holdings_count`、`selection_every_sessions`、Portfolio Weighting 与 `exposure_expression`。SimulationSpec 表示 Simulation Conditions，冻结 `initial_cash_cny`、现有成本、数量、执行及估值合同。两者是 Run 内不可变值，不是新增可编辑资源。
- 对外维持一份规范化定义：沿用现有公共日期、Universe、`formula`、`neutralization` 等字段，在 Strategy 分支增加本金、配权和 Exposure，重命名选股周期；Core 可用上述值对象组织实现，不同时维护重复的嵌套和扁平请求。接受、复用草稿、读取来源及 Track 继承使用相同定义。
- `holdings_count` 保持整数 1–100；`selection_every_sessions` 保持整数 1–20，替代公开字段 `rebalance_every_sessions`。新合同不接受旧名或双写别名；存量输入由显式迁移处理。
- Initial Cash 是必填的有限正数 CNY 金额，使用精确十进制、最多两位小数；允许不足买入一手的金额，由正常数量/现金规则产生现金账户。禁止只缩放显示收益。已有固定 1000 万元输入在迁移时保留原金额，不替换成用户此次研究偏好的 10 万元。
- 新策略配权默认等权，Exposure 默认常量 1；准入时显式规范化并冻结默认值。逆波动窗口默认 20、合法整数范围沿用窗口约束 1–252。目录公布默认值、范围、表达式资源限制及实际启用模型，不暴露未实现形态。
- `get_research_context` 和 `get_alpha_catalog` 继续作为共享发现入口，扩展输入作用域、结果类型、适用运算、依赖、共同指标口径及可用范围。网页与 Agent 使用同一目录，不依赖页面提供 Agent 契约。

### 3. 表达式、共同输入与数据准入

- 复用受限表达式编译器及 Series 执行核心，支持数值/布尔类型、比较 `>`、`>=`、`<`、`<=`、`==`、`!=`、布尔 `and`、`or`、`not` 和纯条件 `if_else`。数值类型与常量、每日共同值、每日每股值的作用域分别检查；不将布尔隐式当数值、不将股票向量隐式压为账户标量。
- Signal 最终输出每股每日数值，沿用 Research Eligibility 和可选 Industry Neutralization 得到 Final Alpha Cross-Section；Strategy 按周期消费选股快照。Exposure 每日输出账户级有限数值 0–1；常量合法，越界不自动裁剪。
- Signal 可用现有六个行情字段、六个财务字段及共同指标。Exposure 可用常量、适用共同指标和运算，不能直接引用个股字段、股票截面 `rank`、持仓、现金、账户盈亏或回撤。共同指标可广播参与股票表达式；两表达式不自动引用彼此，Exposure 不乘入独立 Factor 评价。
- 布尔缺失保持未知；`and`、`or` 任一操作数未知则结果未知，`not` 未知仍为未知。`if_else` 条件已知时只由被选分支决定该位置的值，未选分支缺失不污染结果；条件未知则结果缺失。两分支仍须静态合法、类型兼容，并完整声明依赖和历史窗口。Signal 合法缺失沿用 Missing Alpha Value；Exposure 无效计算不能静默解释为满仓、空仓或保持原值。
- 首版共同指标采用现有数据可构造的等权单 Session 收益和上涨占比，分别作用于本次 Liquidity Universe 及其中一个明确指定的 SW2021 一级行业子集。这是本规格收敛的最小聚合口径：成员按信号 Session 的 Universe Membership 与历史 Industry Classification 确定；不使用当前行业回填过去，不再经过当前 Alpha 或未来标签筛选。
- 成员收益使用截至当日 Close 的调整后 Close 单 Session 收益；完整、有限的前后两次 Close 构成有效样本。等权收益为有效收益的算术平均，上涨占比为收益大于零的有效成员数除以有效成员数，零收益计入分母。返回成员数、有效数及排除原因；无有效样本时指标缺失，不伪造零。确认停牌等沿用现有数据语义，不为聚合额外填行情。
- 目录必须将行业指标标成“本研究 Universe 内的申万一级行业”，公布成员及有效样本口径，不标成全行业或官方指数。行业参数只决定共同输入，不修改选股 Universe。采用目录注册的固定指标身份和受校验行业参数，不开放任意证券查询、任意聚合代码或对象访问。
- 现有 CSI 300 Benchmark 继续用于绩效比较，不从可变 Benchmark Snapshot 向已接受策略注入研究数据，不把已有 Open 冒充 Close。官方指数收盘输入、全行业指数及概念板块不是本版依赖；以后成为研究输入时必须经过相同治理。
- 准入编译 Signal、Exposure、Weighting 的真实依赖，计算联合 Calculation Warm-up、行业需求及资源预算，包含嵌套窗口和收益的前一观察。Warm-up 不计绩效；不能只取 Signal 窗口或后移研究起点。共同指标按各历史 Session 成员构造，定义、成员和字段来源进入冻结身份。
- 继续使用现有发布校验、覆盖、就绪、准入、基础设施重试和计算失败分类。未就绪返回具体问题；非法配置或可确定依赖不足在创建 Run 前诊断。接受后固定输入出现确定性计算错误时报告表达式位置、日期和原因，按现有失败边界处理，DailyTrack 保留上次发布状态。不以猜测历史行情普遍缺失为由增加兜底交易规则。

### 4. Portfolio Weighting

- 每次 Target Selection Update 按 Final Alpha Value 降序及既有 Instrument Identity 决胜顺序扫描候选，应用 Weighting Eligibility，取得至多 Holdings Count 个有效者。以最终入选集合计算权重，非空时非负且合计 1；名单顺序及权重在零仓位期间仍保留。
- 等权：最终 K 只股票各得 1/K。
- 排名加权：最终入选集合第 r 名的原始权重为 K+1−r，再归一化；并列者共享所占名次的平均原始权重。Top-N 边界并列沿用身份排序，不把全 Universe 百分位 `rank` 充当权重。
- 波动率倒数：截至选股 Close 的完整窗口内，调整后 Close 单 Session 收益采用总体标准差；有限且大于零的标准差取倒数后归一化。零波动、合法历史不足或不可用收益令本次 Weighting Eligibility 不成立，记录原因并顺延；基础设施读取失败不伪装成候选不适用。
- 有效候选不足时用剩余者归一化，全部无效时 Target Selection 为空、股票目标金额为零。无隐藏 epsilon、等权替代或强行补足；空名单不改写 Exposure 表达式的返回值。

### 5. 目标、时点与实际账户

- 保持多头、无杠杆、当前合成账户、Board-Lot Rounding、Child Order、Transaction Costs、Raw Open 执行及调整后估值。新买入仍经现有资格、价格、数量和现金检查；Exposure 不是实际仓位硬上限。
- 第一研究 Session Open 是全现金 Backtest Start Baseline；第一次选股在该 Session Close，后续按 Selection Interval 计数。Warm-up 不产生交易，DailyTrack 不重置相位。
- 每个完成 Session Close 计算 Exposure，选股日更新名单及权重；名单未变也形成新配置目标。Exposure 相对上次已决定值变化时独立形成调整；两触发同日发生合并为一个目标，在下一 Research Open 尝试一次先卖后买。
- Target Exposure 乘执行 Open 的交易前 Net NAV 得目标股票金额，不能只乘现有现金。金额在数量与费用之前确定，扣费后不循环反解目标。收盘冻结决策模式、名单、权重及 Exposure，下一 Open 根据实际账户和 Open 价格形成金额与数量。
- 有新 Target Selection 时按新名单、权重及 Exposure 形成完整配置；没有选股更新且 Exposure 未变时，不因价格漂移单独下单。
- 非选股日降仓按执行前实际持仓价值比例缩减至目标股票金额；实际股票价值已不高于目标时，不因减仓决定反向买入。每股先确定自身减仓量，不能额外卖其他股票补偿受阻股票。
- 非选股日加仓或从零恢复，使用最近保留名单、权重和 Strategy Candidate Order 补足买入缺口，不临时重新排名或为重置相对权重额外卖出。总新增买入预算不超过目标股票金额减实际股票价值的正差，且受现金及费用约束。
- 空仓期间正常更新名单。受阻订单当日结束、不逐日自动重试；下一次真正选股或 Exposure 触发从实际账户重新规划。受阻、取整、现金及成本可令实际仓位偏离目标，结果如实呈现。
- 10 万元、约 20% 回撤是用户的研究评价偏好，不自动成为止损规则或未来损失保证。

### 6. 末日、DailyTrack 与恢复

- 回测最后纳入的 Session 正常执行此前已决定、应在该 Open 执行的交易及费用，再记录 post-trade Open NAV；不因结束强平。最后 Close 的下一 Open 决定进入权威续算状态。
- DailyTrack 从成功 Strategy Result 的固定 Tracking Origin 开始，继承 Initial Cash 基线、策略/模拟合同、现金/持仓、累计统计、选股相位和保留目标。只能手动 Refresh；读取或轮询不刷新、不采集数据、不重建账户。
- 续算必需的 Origin 内容归 Track 自己拥有；按既有规则删除源 Run 或源 Run 临时持仓到期，不得破坏已创建 Track 的输入和状态。
- Refresh 固定本次连续后续 Sessions 与 Data Generation；只推进更晚日期，成功时原子发布新增产物、Checkpoint 与 Tracking Head。无新 Session、执行中、失败或重试沿用既有状态合同；失败不发布部分进度、不改变原 Run。
- 续算状态保存已决定的下一 Open 目标值和模式、最近名单/权重、有效 Exposure、决策 Session 及原数据/合同身份。不能只存 Signal 日期，在缓存消失后用新 Generation 重算过去决定。未来决定使用本次 Advance 固定的新数据。
- 前一 Checkpoint 的 NAV、交易及边界观察不可被 successor 覆盖；相同输入及合同下保持 Batch-Incremental Equivalence。不同历史修订版本的新 Run 不适用此等价断言。
- 保留幂等、单次 Advance 排他、取消、Stop 和恢复规则；基础设施 Retry 保持原被接受定义。当前数据重跑使用新 Run；改策略也通过新回测/新 Track，不在旧 Track 改版本。

### 7. Factor Evaluation 证据

- 首版沿用并全部报告 1、5、20 Research Sessions 三个期限，不增加任意期限或标签价格选项。信号 t 的标签从 t+1 调整后 Open 至 t+1+h 调整后 Open，未来标签绝不进入 Strategy。
- t+1+h 超过所选 Research Period 末日时保留 `right_censored_by_research_period_end`，即使更晚历史存在也不越界取标签。返回实际可评价信号区间、可计算日期数和尾部未评价计数；不填零，不当成数据采集异常。
- 保存各日期/期限的 Factor Daily Observation：IC、Rank IC、五组 Forward Return 与组样本数、有效/排除样本及原因、必要覆盖分母。沿用 ties、合法空组、小样本及统计不可定义的既有语义。
- 全期及月/年汇总按信号日期聚合有效每日统计；IC/Rank IC 等日权汇总，ICIR 沿用每日序列样本标准差。月/年分组不重新截断标签，不把股票和日期混成一次相关性，不新增模糊“稳定性得分”。
- Five-Quantile Return 和 Top-Bottom Return 是标签统计，不是扣费可执行组合；网页和 MCP 显式注明口径。

### 8. 永久结果与可查询证据

- Factor Result 保留摘要和每日聚合；Strategy Result 保留摘要、Strategy Daily Observations、Terminal Strategy State/期末实际持仓、真实目标事件、Simulated Orders、Child Orders、Simulated Fills 及实际估值调整事件。Track 查询当前发布持仓，追加本次账户/交易证据，不复制全部历史。
- 事件保留决策及执行 Session、原因种类、来源和稳定逻辑身份。逻辑键独立于 Chunk、Attempt、Retry 和临时数组下标；父目标、订单、子订单和成交可关联。无目标更新日期不必创建永久空事件。
- 成交及账户调整声明执行股数、Raw Open、Raw Notional、费用、Research Settlement、现金增减、Adjusted Holding Units 增减等实际证据。不能用原始成交额替代合成账户真实结算，不能把退市核销伪装成成交。
- 较大统计及事件用现有压缩列式产物；PostgreSQL 管生命周期/manifest，RustFS 存不可变字节。持仓收集与永久事件发布复用同一账户核心，不复制引擎或整段累积到无限增长的内存列表。
- 默认读摘要，明细使用有类型 section。保留 `factor`、`strategy_summary`、`strategy_observations`、`terminal_strategy_state`、`terminal_positions`、`provenance` 等语义并按 kind 提供，新增每日 Factor、目标、订单、成交和临时持仓分区。仅允许 section 支持的日期、股票、期限或事件身份过滤；集合沿用分页上限 50。
- Cursor 绑定 Researcher、资源、固定 Result/Checkpoint 或诊断产物身份、过滤和排序。Track 新发布、Retry、到期或重跑不能令后续页切换数据。按 Research Ownership 和现有 MCP scope 授权，不暴露可绕过授权的对象存储地址。
- 区分完整记录但零条、旧结果未记录、临时产物已过期。永久每日账户观察和期末/当前持仓不依赖临时明细；查净值不能顺带续期持仓。

### 9. 临时 Daily Holding Observations

- 正常成功 Strategy Run 就生成每日实际持仓，Factor Run 不生成，Track 只生成新增 Sessions。记录真实持有股票、执行股数、调整后单位、当时估值及实际权重，时点为 Open 执行与费用之后；读取不使用最新行情重估。空仓日期也保留覆盖证据。
- 每个 Run、Batch 子 Run、每次成功 Advance 新增段各为独立保留单元。到期时间为成功发布时间和最后成功明细读取时间中较晚者加 7 天；服务端统一时间计算，研究日期、排队时间和客户端时间不参与 TTL。
- 7 天来自本轮建议，是本规格默认值，并非用户指定数字。首版不增加多档套餐、永久开关或 UI 保留配置。
- 尚有效的真实明细读取成功后，只续期实际读取单元，包括合法空仓日期；列表、摘要、可用性、状态轮询、健康检查、后台预取及清理不续期。新 Refresh 不续期旧段，其他 Batch 子项完成不续期同组数据。
- 临时内容发布后不可变，独立元数据保存拥有者、来源、覆盖、状态、最后明细读取时间、`expires_at`。不进入永久 Result/Checkpoint 必需对象集合，到期不影响结果完整性、原指标和续算。
- 按有界 Chunk 收集压缩，不保留全 Universe Alpha/Label、逐算子或自然语言逐股日志。上传完整性及失败/取消暂存清理沿用现有发布规则；未完整分区不能宣称覆盖全部日期。
- 到期逻辑状态为 `expired`，物理清理未完成也不重新开放读取；保留小体积到期/来源信息。过期元数据读取不续命，过期不等于有效空数组。
- 原子过期检查先撤销临时拥有引用，再复用 Publication 引用复核删除无人引用字节。读取/续期与过期协调同一状态并保护已获准的有界读取：有效读取先赢则续期，过期先赢则返回过期。禁止按共享桶对象年龄删除或删除 Result、Checkpoint、其他有效产物仍引用的对象。
- 周期性维护做物理删除，失败保留可重试状态，不承诺精确某秒释放。TTL 不永久 pin 原行情、不改变 Data Generation 既有保留，也不把既有永久数据追溯标成可删。
- TTL 限制历史累积，不消除本次写入、峰值和高换手事件成本。容量验收量测行数、压缩字节、内存、写入耗时和清理滞后，计入窗口内产量及持续读取单元，不预设压缩率或固定 GB 承诺。

### 10. 当前数据重跑

- 读过期明细不自动计算。网页“重新回测生成持仓”或 Agent 显式提交，复用原策略、模拟参数和研究日期创建普通新 Strategy Run，按当前合同准入当前 Data Generation，正常排队、预算及取消。
- 新 Run 记录 `source_run_id` 等来源及实际数据/规则身份；旧数据或旧引擎不可用不是前置阻碍。新 Run 内仍固定一致输入，不在执行中混用可变数据。
- 新旧指标可以不同，差异不触发失败或相等门槛，也不承诺差异一定很小。不能改策略凑旧收益、把新持仓塞回旧 Run、覆盖旧指标或称为原始持仓恢复。
- 旧配置在当前合同下非法时返回定位明确的正常诊断，不用旧版本引擎或隐藏参数替换。历史记录可读不等于旧输入可执行。
- Track 历史排障另建当前数据普通回测，从对应原始研究起点计算至调查日期，记录 Track 及发布状态来源；不能从孤立中间日全现金开始冒充连续历史，也不覆盖 Track。正常 Refresh 仍从自身完成状态继续。

### 11. HTTP、MCP 与网页

- 保留资源式提交、状态、结果、Batch、Track 创建/刷新接口。`submit_research_run` 返回规范化定义、资源身份及 accepted/rejected，accepted 不是 completed；状态查询与明细读取分开。
- 保留 `diagnose_alpha_formula` 作局部诊断并区分 Signal/Exposure 上下文；新增 `diagnose_research_spec` 诊断整份配置，复用准入编译、约束及依赖解析。不创建 Run、不占数据 pin、不承诺稍后必可提交；正式提交再次原子校验冻结。
- 状态变更沿用稳定 `request_id`、权限和幂等收据；断线/重复请求不重复建 Run、Track 或成交。当前数据重跑用新请求身份，不冒充原 Attempt Retry。明细读取续期是明确保留副作用，不要求执行或删除权限。
- Research 保留既有工作台，分信号评估/策略回测。Factor 显示信号、范围、中性化和标签口径；Strategy 增加本金、Selection Interval、Weighting/窗口及独立 Exposure 编辑区。固定仓位百分比只编辑同一常量表达式，不持久化两份规则。
- 编辑器共享目录并按作用域补全，诊断定位对应输入。Data 区分个股 6+6 字段与共同指标，显示成员、聚合、可用条件；不新增顶级导航或把衍生指标称为新原始数据源。
- Research Runs 按 kind 显示冻结配置及结果；Strategy 展示绩效、期末持仓和交易，Factor 展示每日/时段评价。临时持仓按日期/股票分页并显示有效期；未记录、空仓、过期分别呈现。摘要不预取持仓。重跑跳转新 Run，标明当前数据与原来源。
- Daily Tracks 保留手动 Refresh，显示固定来源、当前持仓、进度、选股相位、目标及新增交易。下次选股不等于下次可能交易；过期诊断与当前持仓分开，新 Advance 不重画旧边界。

### 12. 数据保留与合同升级

- 使用限定起止版本、备份、执行记录、可验证失败回滚及重复执行的显式迁移；不自动清库、不只改 schema 指纹、不增加运行时旧字段别名或多版本执行分支。
- 存量 Run、Result、Track 的金额、NAV、计算身份及旧附带 Factor 保留。旧策略 Factor 作为归属原运行的历史证据继续可读，不删除、重算覆盖或伪造独立 Factor Run；新策略执行不依赖该证据。
- 旧结果未记录的每日 Factor、目标、成交、持仓不从摘要伪造。等权、固定本金等可证明事实可在迁移规范化，未知历史保持未记录。
- 新末日合同不能仅改版本号、补做旧交易或改写已发布 NAV。只有能保持含义的状态才能迁移为可续算；无法无损迁移的旧 Track 保留可读历史、明确拒绝继续，以新回测/新 Track 建立当前起点。迁移报告列资源和原因，不运行旧引擎维持表面兼容。

## Testing Decisions

以下是实现完成的验收标准。本次规格整理不执行这些产品测试。

| 可观察行为与独立期望 | 公开边界/层级 | 风险 |
| --- | --- | --- |
| 同一 Signal 分别提交两种 kind；Factor 拒绝账户参数，Strategy 无 Factor section/标签依赖，Track 可从无 Factor 策略 Result 推进。标签计算边界使用不可调用的测试实现，策略仍成功，独立 Factor 正常评价 | 输入及 Kernel 模块；各一条真实 Run/Batch/Track 链路 | 只拆按钮、执行/完成条件仍耦合 |
| 10 万与 1000 万各自初始化；同价、同手数规则下手算数量、最低佣金、余款及收益分母。不足一手留现金。NAV 为 10 万、Exposure 为 0.7、相对权重为 0.5/0.3/0.2，目标为 3.5/2.1/1.4 万元，另算费用与取整 | Strategy/数量成本公开模块接口 | 缩放冒充本金测试、现金乘 Exposure、负现金 |
| K=3 不同分排名权重为 1/2、1/3、1/6；前两者同分为 5/12、5/12、1/6。σ 为 0.1、0.2 时逆波动权重为 2/3、1/3；零波动顺延，全无效空名单 | 配权与 Strategy，小型人工数据 | 百分位误用、ties、兜底、窗口漏日 |
| 成员收益为 10%、−2%，共同收益为 4%，上涨占比为 1/2；零收益入分母。历史行业变更仅影响生效后成员，Universe 外股票不混入；改未来价格不影响此前目标 | 成员解析＋表达式；数据治理边界用最小真实发布 | 范围冒充、未来泄漏、当前行业回填 |
| 数值/布尔及作用域成功/拒绝一致；未知不当 false，未选分支缺失不污染结果；Exposure 不能直用个股或越界。联合窗口含 Exposure/Weighting 且研究起点不移 | 编译、准入、Kernel | 两套语言、类型绕过、遗漏依赖 |
| 选股间隔为 5，中间日 Exposure 改变于次日 Open 执行而不重选。100%→30%→0→恢复、空仓中更新名单、双触发、名单同但定期更新、无变化但价格漂移，各有人工目标/订单期望 | Strategy 状态转换 | 未来数据、周期混用、空仓恢复错误 |
| 持仓为 6 万/4 万、股票目标为 3 万，减仓后的目标为 1.8 万/1.2 万；第一只不能卖不增加第二只卖出。目标不变次日无重试，后续真触发可新建订单 | Strategy 既有停牌/涨跌停 Fixture | 补偿卖出、每日重试、硬上限假设 |
| 末日有前日决定则交易计费；首日全现金、末日不强平，末日 Close 目标可在后续首 Open 执行。全区间与不同切点账户、事件键及终态相同，发布边界不变 | Kernel Run/Advance/Chunk＋Track 发布 | 跳过末日、覆盖边界、相位/目标丢失 |
| 工作缓存丢失仍消费冻结目标；新数据修订不改该目标/旧观察。Retry 不重复成交，并发 Refresh 只有一次接受/发布，失败保留上个状态 | 真实 PostgreSQL/RustFS 的 Track/Worker | 缓存冒充权威、重复/部分发布 |
| 标签仅取 t+1 至 t+1+h Open；越研究末日明确右删失。人工同序/反序 Rank IC 为 +1/−1；常量/小样本不可定义。月汇总由每日值等日权核算，跨月不重截断 | Factor 接口及每日产物查询 | 错位、补零、不可核算汇总 |
| 从初始现金、实际结算、费用及核销独立对账现金与两种数量坐标；Chunk/Retry 不改事件键及父子关系 | 既有手工 ledger Fixture＋真实发布查询 | raw notional 冒充现金、局部 ID 冲突 |
| 收集临时持仓与相同输入不收集诊断的核心计算有相同账户/事件；原明细可与当日账户对账，空仓有覆盖，无全 Universe 明细 | Kernel 有界收集＋发布 | 排障改变计算、遗漏、无限内存列表 |
| P 时刻发布初始到期为 P+7 天；P+6 天读明细续到 P+13 天；只轮询仍在 P+7 天过期。空仓读取续期，过期不续期，子 Run/Track 段独立 | 可控服务时间＋真实元数据事务 | 起点错误、轮询续命、整组保留 |
| 读取赢则安全读完并续期，清理赢则过期。共享引用保护、无引用字节最终删除、失败可重试。过期后 Result 可读、Track 可推进；源 Run 删除不破坏 Track 自有 Origin | 真实 Publication/资源模块并发与故障注入 | 引用误删、读删竞争、泄漏、破坏续算 |
| 无旧 Generation，以当前数据重跑产生新 Run；人为修订价格导致新旧不同也成功，原 Result/Track 不变，新结果有来源 | 准入/发布真实依赖＋UI/MCP 闭环 | 精确重放门槛、隐式计算、冒充旧证据 |
| 分页固定来源/过滤，Track 推进不切新 Head。跨 Researcher、错 scope、改 cursor/过滤拒绝；空/未记录/过期可区分，失败读不续期 | HTTP/原生 MCP 真实授权边界 | 越权、混版本、错误续期 |
| 迁移保留旧金额、NAV、Factor 和来源；失败版本/记录不变，重复执行无重复，不能转换的 Track 明确可读不可续算 | 旧合同 Fixture＋真实迁移 | 清库、假版本升级、覆盖旧历史 |

优先扩展现有证据入口，不建立平行测试体系：

- 输入/计算：[Research Kind](../../apps/core/tests/kernel/test_research_kind_contract.py)、[Strategy](../../apps/core/tests/kernel/test_strategy.py)、[手工账户对账](../../apps/core/tests/kernel/test_manual_strategy_ledger.py)、[Factor](../../apps/core/tests/kernel/test_factor.py)、[表达式合同](../../apps/core/tests/kernel/test_alpha_expression_contract.py)。
- 分段/恢复：[Chunk continuation](../../apps/core/tests/kernel/test_research_chunk_continuation.py)、[Tracking columnar](../../apps/core/tests/kernel/test_tracking_columnar.py)、[Batch execution](../../apps/core/tests/kernel/test_research_batch_execution.py)。`test_replaced_boundary_does_not_leave_an_obsolete_peak_or_loss` 原断言旧边界替换，应以新追加不变量替代，同时保留峰值/回撤独立计算覆盖。
- 存储/迁移：[Publication maintenance](../../apps/core/tests/integration/test_publication_maintenance.py)、[Publication records](../../apps/core/tests/integration/test_publication_records.py)、[保留数据迁移](../../apps/core/tests/integration/test_rank_ic_migration.py)、[Track工作缓存](../../apps/core/tests/integration/test_daily_track_working_cache.py)。
- API/交互：[MCP HTTP](../../apps/core/tests/acceptance/test_core_research_agent_mcp_http.py)、[MCP Track](../../apps/core/tests/acceptance/test_core_research_agent_mcp_daily_tracks.py)、[Research表单](../../apps/web/src/research/ResearchWorkspacePage.test.tsx)、[Runs页面](../../apps/web/src/research-runs/ResearchRunsPage.test.tsx)、[Track页面](../../apps/web/src/daily-tracks/DailyTracksPage.test.tsx)。

浏览器组件覆盖模式切换、字段补全/诊断、窗口、草稿和状态；少量E2E覆盖“分别提交两类研究读结果”“回测开始Track后手动推进”“持仓过期后显式新Run重跑”。隔离环境以可控时间推进TTL，不等真实7天，不在每层重复全部数值案例。UI遵守 [DESIGN.md](../../DESIGN.md)，交互验收优先in-app browser，保留关键页面证据。

按 [仓库验证约定](../../AGENTS.md#testing) 先跑受影响定向测试及lint/typecheck；Core单元入口为 `uv run --project apps/core pytest -c apps/core/pyproject.toml --rootdir . <test-file>`，真实依赖复用隔离运行器。跨模块功能最终执行 `pnpm check`，不重复无关发布套件；实际修改镜像/启动边界时才增加对应镜像验证。新增收集属于资源敏感改动：固定数据量比较持股数、研究长度变化时的峰值/写入，保存基线及结果等价证据，必要时纳入既有性能入口，不以预设压缩率验收。

工程验收使用既有Fixture/Replay、可控数据/时钟，不以公网供应商、真实模型或券商为前置。不得触碰 `thesistrace-dev` 的容器数据、数据卷或Dataset Head。证据存于既有 `.local/test-runs/`、`.local/e2e-runs/`；未经执行的链路不声称通过。

## Out of Scope

- 完整Comparison/Experiment编排、参数优化器、自动策略选择、Notebook平台、独立诊断或精确重放服务。
- 循环、有状态`trade_when`、直接账户目标权重表达式、做空/杠杆、优化器、止损止盈、日内/实盘交易；不先暴露未实现schema选项或空抽象。
- 行业筛选Universe、概念/主题、逐股动态所属行业输入、官方行业指数采集、可编辑Benchmark或成本压力实验。行业参数只改变共同条件输入。
- 永久全历史每日持仓、全Universe Alpha/Label、逐算子轨迹、逐股自然语言说明、历史持仓事件还原。
- 为排障永久保留旧数据/引擎，要求当前数据重跑等于旧Result；放宽单次Run冻结或覆盖Track历史也不在授权范围。
- 自动DailyTrack Refresh、在现有Track改策略、Factor/策略复合运行、通用保留套餐。

## Further Notes

本规格是本地issue tracker正式入口。沿用原目录以保持历史链接，目录名comparison不代表当前范围。没有阻止实施的待答产品决定；工程拆分及具体序列化/字段绑定依现有Module合同落实，不再次询问已接受规则。

按可运行切片交付：分类型配置和实际本金；表达式/共同指标、选股配权/每日 Exposure；末日与续算；永久证据/临时持仓、网页/MCP 与迁移。每个改变账户规则的切片同时贯通 Run、Batch、Track 和对应接口/迁移，只公布已能完整执行的能力；整项以全部验收完成为准，不以表单或单次回测成功替代交付。本次 to-spec 仅发布文档，未拆实施 tickets、修改代码、执行迁移、启动清理、删除实际数据、提交或部署。

词义遵循 [CONTEXT](../../CONTEXT.md)。已有设计决定对应 ADR [0040](../../docs/adr/0040-use-one-long-only-top-n-equal-weight-strategy.md)、[0042](../../docs/adr/0042-use-only-scheduled-alpha-snapshots-for-periodic-full-rebalancing.md)、[0045](../../docs/adr/0045-cancel-blocked-open-orders-without-retry-or-substitution.md)、[0046](../../docs/adr/0046-reassess-existing-position-eligibility-only-at-scheduled-rebalances.md)、[0055](../../docs/adr/0055-record-strategy-nav-after-each-open-execution-cycle.md)、[0099](../../docs/adr/0099-make-one-immutable-result-bundle-the-research-run-truth.md)、[0105](../../docs/adr/0105-publish-one-immutable-tracking-checkpoint-per-advance.md)、[0214](../../docs/adr/0214-select-factor-evaluation-or-strategy-backtest-within-researchrun.md)、[0216](../../docs/adr/0216-share-bounded-batch-calculation-and-recover-complete-tasks.md)。本轮同步修正 ADR [0160](../../docs/adr/0160-use-a-small-static-alpha-value-model.md) 的纯数值限制和 [0153](../../docs/adr/0153-use-user-selected-research-periods-and-derived-alpha-warm-up.md) 的Alpha-only窗口，保留静态受限类型、研究区间不变的原取舍。领域文档记录设计，不证明当前已实现。

补充材料：[已答决定](decision-frontier.md)、[三种能力设计过程](three-capabilities-design.md)、[临时持仓](temporary-holdings-design.md)、[前端变化](frontend-impact.md)、[代码审查](three-capabilities-review.md)。若有早期推荐/可选措辞，以本规格为准。最小共同指标的Universe成员口径、输入约束、增减仓预算及读/清理竞争语义属于本次实施定义，不扩大成全行业指数、自由成本模型或新业务模块。

历史材料：[原Comparison](spec-original-comparison.md)、[各轮决定](decision-history.md)、[已撤回按需诊断](on-demand-diagnostics-proposal.md)。本次只检查规格、链接及文档一致性，未运行产品测试。

## Comments

- 2026-09-11：用户追问“数据不够吗”后，修正“板块行情仍需接入”的无条件表述。当前代码已具备个股行情和按生效日期记录的行业归属；可由其构造衍生行业指标。额外指数行情仅在选择相应发布方指数时才是必要依赖，不能将所有板块输入一概描述成缺数据。
- 2026-09-11：用户“按照推荐”确认申万一级行业及板块指标用于仓位条件，保留现有 Universe。本轮产品设计问题已收敛，不再把这两项列为待答；已补充领域定义与实施顺序，未修改产品实现。
- 2026-09-11：用户询问 Exposure 与 Signal 的关系及字段是否相同。补明确同一表达式 Module、不同输入作用域和输出合同；当前个股 6+6 字段不能原样作为账户级仓位输入，共同指标可由两者引用。本次为已选设计的解释，不新增交易功能。
- 2026-09-12：用户接受三种能力方向并要求 grill-with-docs。已将非等权和实际结果明细纳入本版，确认末日正常交易与零波动排除顺延；随后回复“分开运行”确认 Q1，已将信号评估与策略回测分离同步到 Run、Batch、Track 的设计合同。
- 2026-09-12：用户质疑每日持仓对 100 只股票、10 年及批量探索的存储价值。撤回每日持仓历史的默认持久化与任意日期查询，保留汇总/净值、必要续算状态和已确定的真实事件输出；不增加历史持仓重建系统，未改变产品代码或已有数据。
- 2026-09-12：用户随后决定保存有闲置期限的每日持仓，过期后可用当前数据重跑并接受差异。最新合同替代此前不保存/原条件按需重算的备选；建议默认 7 天，实际读取续期，核心 Result 与续算状态独立保留，仍为设计阶段。

- 2026-09-12：按用户 `$to-spec` 发布正式规格，标记 `ready-for-agent`；补齐公共合同、可核算验收及临时持仓规则，未拆实施 tickets 或操作产品数据。
