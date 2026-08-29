# 04 — Idea-to-ResearchRun loop

**What to build:** 让 Researcher 用一句自然语言 Alpha 想法驱动 Mastra Agent 自主读取研究上下文、选择 Research Folder、查询 Catalog、诊断或修正 Formula、提交 ResearchRun、按 Tool Guidance 轮询并解释真实 Result；整个闭环不需要用户手写完整 Alpha 程序或确认按钮。

**Blocked by:** 03 — OAuth-protected MCP read turn

**Status:** ready-for-agent

- [ ] 确定性 Scripted Fake Model 轨迹从自然语言 Idea 开始，使用当前动态 Discovery 中的 Context、Catalog、Diagnostics、ResearchRun Admission、Detail 和 Result Tools 完成一个 Factor Evaluation 闭环。
- [ ] 同一入口也能提交并解释 Strategy Backtest；Researcher 不需要在 Chat UI 选择 Folder、日期、Universe、Neutralization 或 Strategy 参数，Agent 依据对话、MCP Context 与 Tool Schema 决策。
- [ ] 足够明确的请求使用可靠平台默认值，不出现固定后端 Wizard；只有模型判断缺失意图会实质改变 Research 时才在对话中提出 Follow-up。
- [ ] Agent 生成调用者稳定的 Effect Request ID；传输重试、响应丢失和相同 Tool Call 重放返回同一 Core ResearchRun，不创建重复工作或改变原 Command。
- [ ] Correctable Formula Diagnostics 和 Admission Rejection 作为结构化 Tool Result 返回模型，使 Agent 可以修正并再次提交；Auth、Forbidden、Lifecycle、Transient 和 Internal Error 保持其稳定错误语义。
- [ ] 研究被接受后，Tool Activity 显示安全 Run ID 与状态，Agent 自主决定是否按 `retry_after_seconds` 轮询、读取哪个 Result Section 以及何时向用户返回。
- [ ] Agent Host 不实现 ResearchRun Poller、Watcher、Continuation Job、Folder Chooser、Formula State Machine 或隐藏的后台 Run；所有模型步骤受当前固定上限约束。
- [ ] Agent Run 达到终态、断流或超时只停止 Agent 编排；已经被 Core 接受的 ResearchRun 继续由现有 Worker 执行，稍后的 Chat Run 可以通过 MCP 再次找到并解释它。
- [ ] 普通 Markdown 与紧凑 Tool Activity 能显示生成的 Formula、假设、Research 类型、终态指标、结论及前往权威 ResearchRun 页面的安全链接；结构化 A2UI 留给后续票。
- [ ] 浏览器不存在 Confirm-and-run、Approval Interrupt 或直接调用 Core Mutation 的按钮；Research 写入只从 Mastra Agent 通过 MCP 发生。
- [ ] 使用真实 PostgreSQL、RustFS、Canonical Fixture 和 Research Worker 从 Admission 运行至终态；测试断言 Core Frozen Input、Data Generation、Result 和 Ownership，而不逐字断言模型回复。
- [ ] 覆盖合法直接提交、Formula 修正、Admission Rejection、Worker Failure、MCP Transient Backoff、Agent Run 提前结束、Transport Reconnect 和同一 Request ID 重放，所有等待均为有 Timeout 的条件轮询。
