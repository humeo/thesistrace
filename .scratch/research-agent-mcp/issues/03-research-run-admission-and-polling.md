# 03 — 提交并轮询 ResearchRun

**What to build:** 让 Research Agent 通过 MCP 提交完整的 Factor Evaluation 或 Strategy Backtest，获得 durable `run_id`，并通过稳定分页的历史与紧凑详情持续轮询到终态；可修正 admission 问题作为结构化结果返回，transport 重试不会创建重复 ResearchRun。

**Blocked by:** 01 — 建立安全的 stdio Research Agent 上下文闭环

**Status:** ready-for-agent

- [ ] 发布 `list_research_runs`、`get_research_run`、`submit_research_run`，分别要求 `research:read`、`research:read`、`research:execute`，并使用统一 Capability Registry 与现有 ResearchRun module interface。
- [ ] `submit_research_run` 使用当前 Factor Evaluation/Strategy Backtest discriminated contract，完整覆盖 `request_id`、Folder、名称、Formula、hypothesis、日期、universe、neutralization、research kind 及 Strategy 专属边界，不从自然语言推断缺失输入。
- [ ] admission 返回明确的 `accepted` 或 `rejected` structured outcome；accepted 包含 durable `run_id`、当前状态、replay 标记和适用的 `retry_after_seconds`，rejected 包含稳定 issue code、字段或 source range 和可操作说明。
- [ ] 相同 `request_id` 与相同 canonical command fingerprint 在并发调用、进程重启前后均重放原始 outcome 和同一个 `run_id`；相同 identifier 搭配不同输入返回 `IDEMPOTENCY_CONFLICT` 且不创建资源。
- [ ] `list_research_runs` 使用稳定 opaque cursor、默认 20、最大 50、确定性排序，并支持当前 Folder/research kind 过滤；cursor 与过滤条件绑定，不能跨查询重用。
- [ ] `get_research_run` 返回 frozen authoring input、lifecycle、progress、timing、failure/admission summary、key metrics、结果可用性和建议轮询时间，不内嵌大型 Result 或暴露 manifest、checkpoint、attempt、lease、路径、SQL、对象 key。
- [ ] Factor Evaluation 和 Strategy Backtest 都能在隔离的真实 PostgreSQL、RustFS 和 Worker 环境中从 admission 运行到终态，MCP 断开和重新连接不影响执行。
- [ ] 非法输入、未知 Folder、not found、临时依赖失败、终态失败和 Worker 重启有结构化、可判定测试；V1 discovery 中不存在 ResearchRun retry 或 delete Tool。
- [ ] Capability Registry、stdio 协议与真实依赖 acceptance 测试通过，使用有超时的条件轮询而非任意 sleep，并保存必要诊断。
