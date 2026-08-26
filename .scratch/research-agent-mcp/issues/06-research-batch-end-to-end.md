# 06 — 提交、监控并取消 Research Batch

**What to build:** 让 Research Agent 通过四个 MCP Tool 完成 Factor Evaluation Batch 或 Strategy Sweep 的原子提交、分页查找、明细监控、子 ResearchRun 结果读取和授权取消，而不引入 Batch Result、Batch 专属 scope 或 MCP 持久任务。

**Blocked by:** 04 — 分页读取 ResearchRun 语义结果

**Status:** ready-for-agent

- [ ] 发布 `list_research_batches`、`get_research_batch`、`submit_research_batch`、`cancel_research_batch`；读取使用 `research:read`，提交使用 `research:execute`，取消使用 `research:cancel`。
- [ ] Factor Evaluation Batch 接受共享日期/universe/neutralization 与 1–20 个 caller-stable item，每项包含 `item_key`、可选名称、Formula 和可选 hypothesis；零项、21 项、重复 item key 和非法 Formula 被原子拒绝。
- [ ] Strategy Sweep 接受一个共享 Alpha 与 1–20 个 Strategy 配置，每项包含 `item_key`、可选名称、holdings count 与 rebalance interval，并严格执行现有 authoring boundaries。
- [ ] submit 返回 `accepted` 或结构化 `rejected` outcome、durable `batch_id`、replay 标记和轮询建议；并发/重启后的相同 `request_id` 重放原 outcome，不同 fingerprint 返回 `IDEMPOTENCY_CONFLICT`。
- [ ] list 使用默认 20、最大 50 的稳定 opaque cursor；detail 保持 item 顺序并返回 aggregate progress、lifecycle、timing、diagnostic 和 durable child `run_id`，不内嵌无界 child Result。
- [ ] Batch item Result 只能通过既有 ResearchRun Tool 读取，且可完成至少一个真实 child Result 的端到端验证；discovery 中不存在 `get_research_batch_result`。
- [ ] cancel 标记 destructive，并复用独立的 `research:cancel` 权限模型；覆盖合法/非法状态、部分 child 完成、与 Worker 并发、重复调用、冲突 fingerprint 和重启恢复。
- [ ] 两种 Batch 均在隔离的真实 PostgreSQL、RustFS、Research Worker 与 Batch Worker 环境中完成 execution、查询和取消测试，不 mock 自有依赖。
- [ ] Tool Schema、错误映射、权限、分页、幂等、无 Batch Result 负向合同和相关现有门禁全部通过。
