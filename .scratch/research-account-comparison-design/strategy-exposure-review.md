# StrategySpec 与 Target Exposure：首版范围再审

Status: needs-triage

> 历史分析与代码核对记录。用户已接受最后两项板块范围，当前设计以 [首版设计](spec.md) 和 [决策记录](decision-frontier.md) 为准；下文的“待决”或“推荐”描述其记录时点，不是当前待答问题。

2026-09-11。已读取用户引用《解释共同市场条件》全文，并对照当时本地代码。此文记录替代 scope-revision.md 中“首版只扩条件 Alpha”的阶段性推荐。引用中的 assistant 建议本身不视为用户已经批准的领域决定；后续接受记录在 spec.md。

## 推荐

采用结构化 StrategySpec，加入组合级 Target Exposure，保留真实本金。复用同一表达式 Implementation，按 signal / exposure 设不同输出合同。首版不新增持久 Comparison Module、SearchSpace Module 或通用交易语言。

用户在引用中明确目标为 Agent Quant Research。只切换股票评分不能覆盖整体仓位的探索，signal + exposure 更符合意图。但没有证据证明固定 Strategy 一定是最大的收益瓶颈；数据、执行假设与样本外选择仍影响研究质量。

```text
Factor Evaluation = AlphaExpression + ResearchScope
Strategy Backtest = StrategySpec + ResearchScope + Initial Cash / costs

StrategySpec {
  signal_expression
  exposure_expression
  holdings_count
  rebalance_every_sessions
}
```

StrategySpec 是接受后冻结的值，不另建可变策略对象。Factor Evaluation 继续独立，不强迫它接受 StrategySpec。固定多头、等权、合成成交模型通过共享约束公开，不增加只有一个选项的 risk/direction/weighting 配置袋。

## 同一个表达式 Module，两种输出合同

- signal 输出每股每日分数，可将市场共同条件广播到股票截面。
- exposure 输出每日一个有限的 [0,1] 数值，可引用市场序列或常量；首版不读取股票截面、持仓、现金或成交状态。
- 复用 parser、builtin、诊断、字段绑定与资源计算，不复制 Exposure 语言引擎。
- 数值/布尔类型与常量/每日共同/每日每股作用域分开建模；缺失也有明确语义。Market Series 不是不随日期变化的 scalar，股票序列不能隐式缩成组合仓位。
- 比较、布尔、if_else 纳入；不加入通用循环或无期限保持旧信号的 trade_when。

## Target Exposure 不是实际仓位保证

当前 research_kernel/strategy.py:414–416 算交易前 NAV，:452 将 pre_net_nav 分给候选。建议改为：

```text
target_invested_value = pre_trade_net_nav × target_exposure
per_candidate_target = target_invested_value / actual_candidate_count
```

零候选单独处理，不做除法。目标为 0 时现有持仓目标为 0，但仍须尝试受约束的卖出。沿用卖出再买入、整手、费用和现金检查。不能仅将买入预算写成 cash × exposure，否则不能正确降仓。

目标为 0.3 不保证成交后恰好30%；停牌、跌停、价格、取整与费用都能造成偏离。目标为0也不保证全部卖出。它不是任意时点的硬风险上限。目标用交易前 Net NAV，扣费后不循环反解目标。

exposure=1 在相同输入和生效规则下须与现有结果精确等价；不宣称旧模型实际始终满仓。0、0.3、1 均需独立手算及受阻卖出测试。

## 生效时点：第一项待决

用户已选择：每日条件要求降低仓位时，在下一交易日 Open 尝试减仓，选股仍遵循原周期。此决定替代下面共用调仓周期的原推荐。已将 Target Exposure / Exposure Reduction 定义写入 CONTEXT；是否同样每日加仓、沿用哪个股票集合、目标不变是否每日再平衡等尚未回答，不从“这种”推断这些选择。ADR0042 的正式修改待这些语义收敛后记录，当前实现仍只有原定期调仓。

推荐与既有 Rebalance 共用信号日及下一 Open。条件可每天计算，但只有调仓信号触发账户动作。周一调仓、R=5，周二收盘跌破均线，此方案在下次调仓才尝试降仓。

若要求周三 Open 就降仓，则 exposure 每日生效、选股每 R 日更新，需要定义沿用哪个股票列表、零仓恢复、证券中途失效、每日重新下目标和受阻卖单处理；需重开 ADR0042，不是一个乘法改动。收盘输入无论哪种方案都不能影响同日 Open。

## Market Series

推荐先提供一个明确的沪深300收盘研究字段。底层继续 catalog + field_id 绑定，声明市场级作用域与日历。平坦字段名 csi300_close 不必然是坏架构；market("000300.SH").close 的语法也不会自动解决冻结和类型问题。暂不开放任意证券字符串查询或对象访问语言。

现有 Benchmark 是独立的 CSI300 Open 对照历史。研究输入必须治理采集、校验、可见时点、修订、日历、缺失和 warm-up，并进入冻结研究输入；不能从可变 Benchmark 读取最新值注入已接受研究。新增收盘字段不是现有 Open 字段改名。

整条策略的字段依赖取两表达式并集，warm-up 至少取最大值，工作量覆盖两者；共享 Alpha 的身份仍独立于 exposure 依赖。

## 缺失或非法值：第二项待决

> 用户要求先系统分析、按原因处理。以下统一失败推荐已被 [数据就绪与恢复分层](data-readiness-review.md) 替代：区分未接受、未就绪、临时执行失败与固定输入确定无效；DailyTrack 失败不改变原 ResearchRun Result。

推荐：静态非法在准入拒绝；执行需要的 exposure 缺失、非有限或越界时明确失败，返回日期和原因。DailyTrack 保留最后成功 checkpoint，不发布部分 Advance。不能静默当0、1、保持旧值或 clamp。

若要缺失时清仓，必须是一项显式研究规则及可见证据，不是通用 fallback。这样才能区分市场择时和数据缺失。if_else 已知条件下未选分支缺失，与条件未知不同；全部分支仍需编译合法。非使用日的缺失是否影响账户，要在生效时点确定后定义。

## 结果和历史演进

> 后续范围修正：用户要求聚焦增加回测功能。以下新增目标轨迹/逐股诊断证据的“最低必需”建议撤回，不是首版交付要求；复用现有结果合同，仅在新定义和执行/续算状态确有变化时进行必要演进。不为新增诊断历史启动结果迁移。

最低必需证据：signal session、execution session、该次生效 target_exposure、actual_exposure、是否调仓和偏离原因。每日表达式值与上次实际生效目标必须分开。已有 cash_ratio 不能代替目标轨迹；这部分不能推迟到完整逐股账本以后。

Factor 统计仍评价 signal，不乘 exposure；零仓位日仍可有 Factor 证据。只统计入场日须另标样本选择与分母。Agent 应区分信号证据与组合证据，可以对照同条件固定仓位基线；更高回测 Sharpe 不是择时有效性的自动证明。

全程 exposure=0 应允许形成连续现金账户；零收益/零费用，可无法定义 Sharpe。源码核验：research_run/result.py:573 以首次 rebalance 取 entry_session，不要求真实成交。不能把0仓位实现成跳过 rebalance，否则入场可能退到末日，扭曲统计。daily_track/checkpoint.py:129 的恢复允许空持仓，仍须保留完整观察和终态。该场景尚未运行，因为当前无 exposure 参数。

新目标轨迹涉及 Result/Tracking 不可变格式，须显式迁移、备份、引用保持、回滚和重复执行验证。历史未记录值标明不可用，不在客户端猜测；旧固定目标1的回填须由迁移确认合同，而不是隐藏运行时兼容。

## Batch 和 DailyTrack 的具体修改点

- research_batch/execution.py:1094 校验共享输入时排除 strategy。exposure 放 Strategy 条件，signal 相同仍可共享 Alpha/Factor；把 exposure 依赖混入 signal 的身份会误破坏共享。
- research_run/service.py:3897、:3924 当前从单 compiled Alpha 计算依赖与资源，须扩为整条策略的需求。
- research_batch/execution.py:1137 的 item 准备使用 field_bindings={}、effective_lookback=0，只取执行事实。此处会漏读 exposure 数据，必须修改。
- daily_track/calculation.py:129、:212 的正常 Advance 与缓存重建仅按 Alpha 窗口/字段读取；checkpoint.py:302 也只恢复既有 Strategy 参数。纯表达式虽不用保存事件记忆，仍需贯穿这些路径。
- 维持完整 Alpha/Strategy 恢复，不新增逐节点持久调度；普通/Batch/增量须证明一致。

## Agent Interface

复用 get_research_context/catalog 公布真实合法类型、参数上下限和数据范围。SearchSpace 的建议候选点和搜索预算属于研究计划，不另建一套与 Core 校验可能分叉的规则。

submit_research_run 的 Strategy 分支接受 StrategySpec；Factor 分支保持 Alpha。诊断给出 signal/exposure 字段路径。get_research_run_result 返回信号与目标/实际仓位证据；HTTP/MCP 共用合同。预检可选；策略 Run 已含 Factor 结果，不强制额外先跑 Factor。

保留只读 compare_research_runs；新建跨期实验对象继续延后。Agent 研究计划还需要探索/验证区间与试验预算，不能因限制了候选点就声称避免过拟合；这不要求立即新增优化器或编排 Module。

## 交付与正式文档

按层实现：表达式/作用域和冻结市场输入 → 本金与 exposure 计算 → Result/Tracking 演进及网页/MCP 完整闭环 → 只读对照。至少到第三层才算首版完整可用。

正式 CONTEXT 尚未新增 StrategySpec / Exposure Expression / Target Exposure：当前是推荐。用户确认定义后按 domain-modeling 立即记录。需检查 ADR0040 的组合构造扩展、0042 的时点、0160 的类型、0099 的保留及市场研究输入决定。

本轮 frontier：Q1 exposure 共用定期调仓还是每日独立生效；Q2 所需 exposure 缺失/非法是否按推荐失败。原具体未成交解释粒度继续待答；目标/实际轨迹是此次推荐的最低必需证据。
