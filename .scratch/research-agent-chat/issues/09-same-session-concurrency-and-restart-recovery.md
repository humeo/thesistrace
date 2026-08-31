# 09 — Same-session concurrency and restart recovery

**What to build:** 让同一 Researcher 在两个浏览器或设备打开同一个 Chat Session 时看到同一 Agent Run，并由 CopilotKit AgentRunner 保持一个 Thread 只有一个活动 Run；断线、重连和 Agent Host 重启不会重复提交 Message，已经进入 Core 的工作继续独立运行。

**Blocked by:** 04 — Idea-to-ResearchRun loop; 05 — Session history and independent deletion

**Status:** ready-for-agent

- [ ] 两个已认证浏览器上下文打开同一 opaque Session ID 时读取同一 Thread、Messages、当前 Run ID 和 Terminal History，而不是创建客户端本地副本。
- [ ] 第一个客户端开始一个由 Barrier 控制的长 Scripted Run 后，第二个客户端能观察 Running State；Composer 在两端禁用且不会发送重叠 Turn。
- [ ] 绕过 UI 直接提交第二个同 Thread Run 时使用 AgentRunner 的支持行为明确拒绝或绑定现有 Run，不产生第二个 User Message、模型调用、Tool Call 或自定义 `session_busy` Product State。
- [ ] 不同 Chat Sessions 可以并行运行，只有 AgentRunner 和固定 Deployment Capacity 限制它们；不存在全账号单 Run 锁或持久自定义 Queue。
- [ ] AG-UI Stream 中断后重新打开 Session 会以相同 Run Identity 重放已经持久的 Event 和 Message，不自动重发最后一条 User Message，也不重复已完成的 MCP Mutation。
- [ ] Agent Host 在至少一个 Tool Outcome 完成后重启时，Thread、Messages、完成的 Tool Outcome 和 Core IDs 保持可见；未完成的 Model Invocation 进入明确 Terminal Failure，而不是静默继续或切换模型。
- [ ] 如果重启或 Wall-time 发生在 Core 接受 ResearchRun 之后，真实 Worker 继续到终态；后续 Agent Run 能通过保留的 ID 或授权 List Tool 再次读取并解释结果。
- [ ] Active Run 期间不允许 Session Delete，且删除不作为 Interrupt；Run 终态后按 Session Ticket 的独立删除契约工作。
- [ ] Cross-Researcher Client 无法 Attach、Observe、Resume 或判断另一 Researcher 的 Run 是否存在；所有结果与 Unknown Session 一致为 Not Found。
- [ ] 并发、重连和重启测试使用固定 Clock、UUID、Seed、Barrier 与有 Timeout 的条件轮询，不使用任意 Sleep；失败保存安全 Event Order、Run ID、Dependency State 和进程退出证据。
- [ ] 真实浏览器验收覆盖两个 Context 的 Running/Terminal 可见性、Composer 状态、重连和不同 Session 并发，同时证明只有一个有序 Turn 被持久化。
