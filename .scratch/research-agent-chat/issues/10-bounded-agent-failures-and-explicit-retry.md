# 10 — Bounded Agent failures and explicit retry

**What to build:** 让 Chat 对模型、Provider、Auth、MCP 与 Agent 执行上限的失败提供稳定、可理解且可恢复的终态：保留已经完成的 Message、Tool Outcome 与 Core Resource，不自动切换模型或启动隐藏 Continuation，由 Researcher 明确重试或更换注册模型。

**Blocked by:** 04 — Idea-to-ResearchRun loop

**Status:** ready-for-agent

- [ ] 定义稳定的 Browser-visible Failure Categories，至少区分 Authentication Required、Agent Unavailable、Invalid Model、Unsupported Reasoning、Provider Authentication、Provider Rate Limit/Timeout/Refusal/Malformed Stream、Agent Limit、MCP Authentication、MCP Transient、Tool Rejection、Tool Error 与 Internal Failure。
- [ ] 每类错误通过 AG-UI 形成一个且仅一个 Terminal Run State，显示安全说明和合法下一步；不得留下永远 Streaming、空白回复或与持久 Run 不一致的 Browser State。
- [ ] Provider 失败绝不自动调用另一个注册模型、改变 Reasoning Effort 或重放 User Message；历史 Run 记录实际失败模型，Researcher 可在新 Run 中重试或选择另一个 Catalog 项。
- [ ] Agent Run 固定限制 Message Bytes、Context Tokens、Output Tokens、Tool Result Bytes、Tool Steps 和 Wall Time；超过限制在相应最早边界失败，不进行无限截断、无限 Tool Loop 或后台继续。
- [ ] Step 或 Wall-time 终止只结束 Agent Run；已完成 Tool Outcome、A2UI 之前的持久内容及返回的 Core IDs 保留，已经 Admission 的 Core 工作不被 Cancel 或 Stop。
- [ ] Auth Session 在新 Run 前失效、撤销或 Deactivate 时不交换 Token并显示登录状态；MCP Token 或 Scope 失败不降级为 Anonymous、旧 Token 或直接 Core API。
- [ ] MCP `TEMPORARILY_UNAVAILABLE` 仅按 Tool Retry Guidance 和 Mastra 当前 Run Bounds 重试；不可重试错误、Admission Rejection 和 Formula Diagnostics 不被粗暴重试成重复 Mutation。
- [ ] Registry 重启后移除历史 Thread 当前模型时保留旧 Run 标签，但下一次发送前要求选择 Enabled Model，不静默改为默认模型。
- [ ] Title Generation、Usage Accounting 或非关键呈现失败不回滚已经成功的主 Agent Run；这些独立失败有明确状态且不伪造成功数据。
- [ ] Scripted Providers 确定性覆盖 Timeout、Rate Limit、Bad Credential、Refusal、Malformed Event、Output Limit、Unexpected Error 及恢复路径；普通测试不访问公网或依赖 Provider 文案。
- [ ] 浏览器测试验证 Error Copy、Retry、Model Change、无 Duplicate Message、已完成 Tool State 保留、Core Work 独立及键盘 Focus；断言行为而非错误的逐字长文本。
- [ ] 失败测试输出安全 Trace ID、Run ID、Model Key、Reasoning、Step、Duration、Dependency Status、Seed 和退出码，为下一张 Telemetry Ticket 提供封闭 Metadata 输入。
