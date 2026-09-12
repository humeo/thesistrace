# 首版范围复议：条件 Alpha 与只读结果对照

Status: needs-triage

> 历史范围论证。后续已经接受组合级 Target Exposure 和首版行业指标范围；当前设计以 [首版设计](spec.md) 和 [决策记录](decision-frontier.md) 为准。下文未决问题和只读对照提案不作为当前实施要求。

日期：2026-09-11。依据用户引用的 ChatGPT 讨论（已读取全文）及当时本地代码定向核验，记录替代早期 Comparison 提案的中间方案。本文记录时尚未收敛的内容，以后续 spec.md 的接受记录为准。

## 调整后的推荐

首版保留真实本金全链路，扩展有限的条件 Alpha 表达式，让一个完整表达式作为普通 ResearchRun 在连续账户中运行。已有结果对照采用 ResearchRun 的有界只读 Interface。暂不新增 Comparison 表、实验生命周期、比较 Worker 或自动创建跨日期案例的 Module。

这改变的是交付重点，不是保证“只改 parser 就完成”。Alpha Language、Kernel、catalog、资源估算、执行恢复和公开 MCP 契约必须一起验证。

## 对引用讨论的纠正

1. 当前不存在 trade_when / if_else：alpha_language/language.py:254 显式拒绝 Boolean；:304 起只接受一元负号和四则运算，最终拒绝其他语法。research_kernel/alpha_builtins.py:321 起目录只有 12 个数值/时间序列 builtin。
2. Alpha 与 Strategy 是不同领域概念。Alpha 输出排序分数；Strategy 按 ADR0040 / ADR0042 使用固定 H/R 做 TopN 等权与定期换仓。条件 Alpha 可以换评分逻辑，但不能单靠它切换 H/R、账户杠杆、暂停调仓或立刻清仓。
3. trade_when 的语义必须先定义，不能既把第三参数写成 exit_condition，又在示例中传 quality_alpha 当 else 分支。若采用有状态信号语义，它保留的是 Alpha Value；不等于保留实际持仓。退出输出缺失信号也不自动产生即时卖单。
4. 通用循环不是当前需求的必要条件。有限 ts_* 与布尔聚合可表达窗口统计。持有直至事件发生的状态，仍要单独定义初始化、失效与延续；它不因藏在函数名里就变成有限 lookback。
5. index_close 不是当前 Alpha 字段。data/fields.py:207–217 只组装现有 Market/Financial fields；独立 Benchmark Snapshot 使用 CSI300 Open，职责是业绩对照（ADR0231）。若以指数判市场状态，需要明确可见时点、字段、日历对齐、广播、warm-up 与数据冻结，不可从可变 Benchmark 读取最新数据注入历史 Alpha。
6. 单股 close > ts_mean(close,60) 是逐股条件，不是全市场共同状态。即使加 if_else，也不能将两者混称为“牛熊切换”。
7. 乘法掩码不是一般 if_else 替代品：0 乘缺失值仍可能缺失；未选分支的数值不可用不应自动污染所选分支。条件未知也不能默认为 false。

## 最小推荐 Interface

### 表达式

先定义比较、布尔和 if_else(condition, when_true, when_false)。根输出仍为 Numeric Series；条件具有明确 Boolean/unknown 语义，不允许任意数值隐式转真。窗口布尔聚合按具体用例加入，不为了目录完整而一次实现全部。

编译须验证所有分支类型/字段/语法；计算结果的 missingness 依赖选中分支和条件。静态 lookback、依赖字段及资源上界按所有分支的需要保守估算，不能只算当下选中的分支。rank 等跨截面算子维持既定截面语义，不按当前条件临时缩小排名集合；如需要 conditional universe，另行定义。

纯条件表达式不能读取未来数据，也不直接发订单。切换的实际交易仍按现有 Rebalance schedule 和下一 Open 执行。若用户要求状态触发即时退出，必须重新审视 ADR0042，而不是把行为埋进 Alpha builtin。

有状态 trade_when 不作为默认一起实现；先回答它究竟保存分数还是控制交易。状态何时开始、长期未触发、股票进出范围、跨 chunk、DailyTrack 延续等语义，需在实现前明确。

子任务核验：research_kernel/research_chunks.py:388 的 continuation 不含任意表达式节点状态，alpha.py:116 的 evaluator 没有 prior-state 输入；daily_track/checkpoint.py:76 的 alpha_state 保存定义元信息而非各证券的持有信号。若最后一次更新早于 252 日有限窗口，不能恢复无期限旧信号。纳入这类算子须贯穿 Run 终态与 DailyTrack checkpoint，并满足 ADR0108 精确等价。状态读取账户持仓/现金还会改变现有共享 Alpha 前提；仅保存信号且初态一致则不必取消共享计算。

### 只读已有结果对照

拟议 compare_research_runs({run_ids: [...]})，2–20 个去重后的明确 Run ID；沿用 Researcher 身份和 research:read。由 ResearchRun Module 提供统一有界投影，HTTP/MCP 是两个 Adapter，不额外创建 Comparison 实体。

返回每个 Result 的已冻结输入、实际区间、Generation/计算合同身份、可用指标和差异分类。字段区分不同 Alpha、H/R、本金、费用、区间和数据/计算条件。不自动宣称相同 Generation 就统计可比，也不把不同长度累计收益自动排序为最优。

读操作不提交新 Run、不重算、不自动补齐费用或诊断、不持久化一份新结果。缺失/无权资源沿用不泄露存在性的处理；未完成、已失败等状态与数值 0 区分。具体部分成功/整体拒绝策略留待比较 Interface 细化。

新的 Run 仍由 submit_research_run / 同周期 submit_research_batch 接受；公开工具不能暗中以多次提交假装原子同代。新增实验准入对象推迟到确有整组一致性需求时。

### Agent 使用

get_alpha_catalog / diagnose_alpha_formula 展示和验证真实新增语义；get_research_context 公布本金和资源约束；submit_research_run 接受完整条件公式与本金；get_research_run_result 获取连续账户；compare_research_runs 对照已有结果。无需每个 builtin 一个 MCP 工具。

## Module 修改范围

- alpha_language/models.py、language.py：值类型、解析/诊断、规范表达式。
- research_kernel/alpha_builtins.py、alpha_expression.py、alpha.py：统一数值与列式执行语义、静态依赖及资源估算。
- research_run 与 research_kernel/strategy.py：本金贯通普通、Batch、continuation、DailyTrack。
- data：仅在选择指数/市场共同条件后扩展受治理的研究输入；与 Benchmark 职责分开。
- research_run：只读多 Run 事实投影。
- research_agent 与 HTTP/web：共享 catalog、输入、错误和结果投影。

验证包括三态条件、未选分支缺失、跨截面 rank、未来数据无影响、各分支 warm-up、普通/Batch/增量一致性、本金独立手算和 MCP 发现/诊断/提交/读取闭环。涉及新状态或市场输入时先完成相应数据/恢复合同。

## 本轮待决定的 frontier

Q1. 条件仅选择评分表达式，并沿用既有 H/R；还是还要控制保持持仓/立即退出？推荐首版前者，将 trade_when 的状态含义独立明确后再纳入。

Q2. 条件首先针对每只股票自身，还是必须让整个组合根据共同市场/指数状态切换？用户原始用例指向后者；推荐如果这是验收目标，就把一种明确市场输入一并纳入首版，不能用逐股趋势示例替代。

上一轮关于“必须解释具体未成交原因”的问题尚未得到用户回答。此项不因新的引用讨论而自动撤销或决定；保留在 grilling.md 后续收敛。

## 文档状态

原三份独立方案保留为备选证据。正式 CONTEXT 和 ADR 尚未写入新名词：引用讨论中的建议不是用户已确认的取舍。已确认的定义再按 domain-modeling 立即记录。
