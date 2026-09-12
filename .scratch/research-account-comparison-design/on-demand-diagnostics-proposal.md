# 按需生成持仓排障明细（历史备选）

Status: needs-triage

> 本提案已由用户后续提出的 [临时每日持仓设计](temporary-holdings-design.md) 替代：正常运行即保存每日持仓，按读取续期并到期清理；过期后允许用当前数据重跑，无需重现原数据版本。下文保留提案当时的分析，不作为当前准入、结果一致性或交付要求。

2026-09-12。用户希望 Agent 在需要时能检查每日持仓，同时避免所有回测永久保留完整持仓历史。本文是基于当前代码的建议方案，尚未作为已接受的首版交付要求，也未修改实现。既有范围仍以 [三种能力设计](three-capabilities-design.md) 为准。

## 建议：先读已存证据，再按需生成临时明细

普通回测保持已有指标、每日账户汇总、完整终端状态，以及三种能力设计已纳入的目标/订单/成交事件。Agent 先定位异常日期、成本、目标变化和成交受阻；需要看到逐股持仓时，再请求一小段诊断明细，不为全部候选策略默认生成完整历史。

示例：研究包含 100 只股票和约 2500 个 Session，Agent 怀疑某 10 个 Session 的降仓没有按预期发生。诊断产物只展开这 10 个 Session 的实际持仓、保留目标、当次目标、订单/成交及实际受阻信息，持仓部分约 1000 条；不保存全程约 25 万条。这里减少的是输出和存储，计算仍可能需要从原研究起点推进到所查日期，不能把 10 天输出误称为只算 10 天。

## 现有代码落点

- [Strategy](../../apps/core/src/thesistrace/research_kernel/strategy.py) 的 `run_strategy` 已接受可选 `ledger`，其中有 session、signal、orders、fills、rejections、cash、positions、NAV 和 valuation events。它目前用列表收集，不能直接作为无限区间的持久化诊断实现。
- [主 Chunk 路径](../../apps/core/src/thesistrace/research_kernel/research_chunks.py) 复用 Strategy 核心，但没有打开上述 ledger，并清理分段订单数组。实现诊断应在这条主路径增加按日期筛选的有界输出收集；不能再建一套简化回测或先积累完整历史再过滤。
- [Run 完成](../../apps/core/src/thesistrace/research_run/service.py) 与 [Track 发布](../../apps/core/src/thesistrace/daily_track/service.py) 会释放 Generation pin。[Data 生命周期](../../apps/core/src/thesistrace/data/lifecycle.py) 的保留根包含 Head、active pins、live candidates；保存 Result 的数据身份不等于永久保留对应输入字节。
- 回测与续算的终点合同变化已在 [当前设计](three-capabilities-design.md) 中接受。当前合同重跑不能冒充旧合同的原始记录，也不因此加入运行时旧引擎兼容。

## 生成与验证规则

1. 诊断绑定一个不可变 Run Result，或 Track 的明确发布版本。先检查原策略/模拟定义、实际使用的数据及计算合同是否可用；开始任务时固定并保护所需输入，避免检查后被回收。
2. 原范围和选股相位保持不变。只有存在完整、匹配且早于所查区间的可恢复状态时才能从该状态开始；否则从原 Origin 推进。不得将所查区间第一天重新初始化成全现金账户。股票过滤只控制输出，不能改变原 Universe、排名、配权或账户执行。
3. Track 跨多个 Advance 时分别使用当时各段的数据身份和已发布状态，不能把全段换成最新 Generation。既有发布检查点可以复用；首版不为诊断新增所有 Chunk 的永久恢复点，不改变 Batch 只恢复完整任务的决定。
4. 在同一 Strategy 核心实际执行处收集受限日期的证据；持仓包含实际数量、估值/权重和现金，目标与订单区分决定时间和尝试执行时间。请求区间之外不积累完整 ledger；输出按行数、字节和运行预算限制，分页读取。
5. 将重算产生的每日账户数值及可用的交易事件与原发布证据核对。状态说明为一致、出现差异或无法按原条件生成；若不同，保留首个差异的定位证据。不能仅因为使用了相同表达式或净值一致，就声称证明了所有历史持仓完全一致；明细标明是按原条件重新计算的诊断证据，不是原运行保存的快照。
6. 诊断产物有明确到期时间，按同一来源版本和请求范围缓存复用，到期清理；原 Result、已发布 Track 及其既有保留规则不受影响。任务可取消并受现有 Researcher 权限、资源和并发限制约束，不在普通结果读取时隐式发起昂贵计算。

旧数据或原计算合同不可用时，直接说明无法生成忠实于原条件的明细。Agent 仍可读取已保存的原摘要、终端状态与事件；使用新数据/新规则的研究必须作为新的对照运行明确提交，不能自动替换原条件。

## Agent 与网页的调用形态

在现有 ResearchRun / DailyTrack Module 内提供所属资源的诊断操作，共用 Worker、权限、取消和产物查询，不增加新研究类型、独立 Trace 服务或通用实验编排。

以下仅说明 Interface，名称与字段尚未发布：

```text
request_run_diagnostics(
  run_id,
  from_session,
  to_session,
  instruments?,
  sections = [positions, targets, orders, fills]
)
  -> diagnostic_id, accepted/unavailable, execution_scope, expires_at

get_run_diagnostics(diagnostic_id, section, cursor)
  -> status, source_identity, consistency_check, rows, next_cursor
```

请求接受前说明实际计算范围及可用预算；排队中不承诺完成或确定到期时点，产物发布后给出明确 `expires_at`。网页可在选定研究上指定区间查看诊断进度和结果，MCP 使用同一合同。过期产物返回明确状态，是否再次生成由显式请求决定。

## 与事件和稀疏快照方案的比较

| 方案 | 主要收益 | 代价与限制 |
|---|---|---|
| 默认保存完整每日持仓 | 原运行的逐日明细可直接读取 | 每次研究都承担持久历史成本 |
| 保存全部状态变化并配置稀疏快照 | 可从事件恢复持仓数量，减少从起点重算 | 必须完整记录非交易调整；历史估值还需要当时价格/规则；高换手时事件也多 |
| 按需使用同一核心生成临时明细 | 正常批量研究不承担完整历史输出，复用已有计算 | 消耗重算时间；原输入和合同不可用时无法忠实生成 |

事件加快照是成熟的历史状态恢复思路，快照频率是在存储与恢复耗时之间取舍；完整 Event Sourcing 还引入事件版本、排序、投影和幂等负担。[Microsoft Event Sourcing pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing)。本方案优先复用已有 Result、真实事件与 Strategy 核心，不把整个账户改造成另一套事件存储权威。稀疏状态缓存可以在实测诊断重算成本后作为优化讨论，而非本次前置架构。

## 验证重点

- 相同固定输入下，诊断收集不改变净值、费用、目标、订单/成交和终端状态；过滤只影响输出。
- 从完整匹配状态开始与从原 Origin 推进一致，覆盖跨选股相位、空仓恢复、交易受阻与 Track 的不同数据段。
- 数据保护、当前合同约束、来源权限、取消、到期清理和分页限制通过真实依赖验证；差异结果不改写原 Result。
- 量测正常 Run 是否引入额外持仓历史，以及诊断计算时间、峰值内存、产物字节数。最终缓存期限和预算基于这些测量，不虚构压缩率或节省比例。

本次为设计建议；未运行产品测试、创建线上诊断、修改原始结果或改变数据保留政策。
