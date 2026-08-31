# 08 — Safe DailyTrack flows through Chat

**What to build:** 让 Researcher 在 Chat 中要求持续跟踪一个成功 Strategy 时，Agent 使用当前 Discovery 返回的安全 DailyTrack Tools 完成 Start、状态读取、结果解释，以及在合法情况下的 Refresh 或 Retry；Stop 始终因 Scope 缺失而不可见。

**Blocked by:** 06 — Validated A2UI research surfaces

**Status:** ready-for-agent

- [ ] Scripted Fake Model 从自然语言请求或当前 Thread 中的 Strategy ResearchRun ID 开始，通过 MCP 验证 Origin Run 并提交一个幂等 DailyTrack Start。
- [ ] Agent 使用当前 Discovery 返回的 DailyTrack List、Detail、Result 及所有 `tracking:execute` 安全动作；Host 不维护固定 Tool 名称清单，因此 Core 新增或移除授权 Tool 时以下一次 Discovery 为准。
- [ ] 对当前合约支持的 Refresh 和 Blocked Retry，Agent 依据 Tool Description、Lifecycle 和结构化结果决定是否合法、是否调用以及是否继续轮询；Host 不实现 Refresh/Retry 状态机或调度器。
- [ ] Start、Refresh 与 Retry 使用稳定 Request ID；Transport Retry、响应丢失、并发重放和 Host 重连不会创建第二个 Track 或重复同一业务动作。
- [ ] A2UI DailyTrack Surface 展示 Track ID、Origin ResearchRun、状态、Data Through Session、Block Reason、最新 Observation、关键指标、Provenance 和前往权威 DailyTrack 页面的 Navigation。
- [ ] Agent 能解释 Active、Blocked、Refreshing、Succeeded-like current output 及结构化失败，不把 mutable observations 描述成新的 immutable Research Result，也不暴露 Checkpoint、Lease 或 Storage Key。
- [ ] Built-in Agent Grant 不包含 `tracking:stop`，因此 Stop Tool 不出现在 Discovery，页面不渲染 Stop/Confirm Action，伪造或陈旧调用仍由 Core 拒绝且 Product State 不变。
- [ ] Chat 生命周期不拥有 DailyTrack；Agent Run 结束、Chat 删除、Stream Disconnect 或模型失败不停止已经存在的 Track 或其后续 Worker Advances。
- [ ] 使用真实 PostgreSQL、RustFS、Tracking Worker 和 Fixture Data 验证合法 Start、已存在 Track、Active Refresh、Blocked Retry、非法 Lifecycle、依赖暂时不可用、Idempotent Replay 和 Result 读取。
- [ ] 在完成 ResearchRun、Research Batch 和 DailyTrack 切片后，契约测试证明 Agent Host 对当前四个授权 Scope 的整个 Discovery 结果零遗漏直传 Mastra，并且没有 Host 级 Partial/Full Tool 模式。
- [ ] 真实浏览器可以演示从 Strategy 结果到 DailyTrack 状态与 Observation 解释的闭环；测试以 Core 资源和可见行为为断言，不依赖模型逐字内容。
