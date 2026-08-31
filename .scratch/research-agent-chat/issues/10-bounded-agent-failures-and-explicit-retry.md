# 10 — Bounded Agent failures and explicit retry

**What to build:** 让 Chat 对模型、Provider、Auth、MCP 与 Agent 执行上限的失败提供稳定、可理解且可恢复的终态：保留已经完成的 Message、Tool Outcome 与 Core Resource，不自动切换模型或启动隐藏 Continuation，由 Researcher 明确重试或更换注册模型。

**Blocked by:** 04 — Idea-to-ResearchRun loop

**Status:** complete

## Implementation plan

1. Define one closed failure contract shared by the Agent boundary and Chat UI.
   Preserve stable safe categories and allowed next actions, not provider text,
   raw exceptions, tokens, or internal payloads. Persist the terminal category
   in the existing Run metadata and replay it unchanged. Pre-admission Auth /
   selection failures must not create a durable Turn.
2. Use the pinned providers' typed errors and Mastra-supported model settings /
   lifecycle callbacks. Bound provider calls, context estimates, output, Tool
   result bytes, model steps and total Run time without another planner,
   queue, fallback model or automatic User Message replay. Reuse the existing
   usage seam; invalid accounting remains explicitly unreported and cannot
   overturn successful research.
3. Classify MCP preparation / transport failures separately from correctable
   structured Tool results. Pass the full discovered Tool inventory and Core
   retry guidance through unchanged. Enforce the Tool-result byte boundary
   before Memory/model ingestion; stop fatal failures before another step.
   Diagnostics and admission rejection remain available for model-led repair.
4. Render safe terminal errors with explicit retry, model-selection, login or
   reconnect actions. A retry creates a new Run only after the user chooses
   it; reconnect never resubmits. Preserve completed messages, Tool outcomes,
   resource IDs and historical model labels, including after registry change.
5. Add deterministic provider faults and lower-level red/green regressions;
   prove HTTP/AG-UI terminal counts, persistence, explicit retry, model/effort
   identity, bounds and independent title/usage behavior with real isolated
   PostgreSQL. Extend final-image browser coverage for failure copy, keyboard
   focus, model changes, retained Tool state and independently completed Core
   work. Export only safe metadata for the telemetry ticket.
6. Run affected deterministic, PostgreSQL and final-image gates. Review the
   same staged SHA256 independently on Standards and Spec, fix and re-review,
   update this tracker, and commit Issue 10 alone before beginning Issue 11.

- [x] 定义稳定的 Browser-visible Failure Categories，至少区分 Authentication Required、Agent Unavailable、Invalid Model、Unsupported Reasoning、Provider Authentication、Provider Rate Limit/Timeout/Refusal/Malformed Stream、Agent Limit、MCP Authentication、MCP Transient、Tool Rejection、Tool Error 与 Internal Failure。
- [x] 每类错误通过 AG-UI 形成一个且仅一个 Terminal Run State，显示安全说明和合法下一步；不得留下永远 Streaming、空白回复或与持久 Run 不一致的 Browser State。
- [x] Provider 失败绝不自动调用另一个注册模型、改变 Reasoning Effort 或重放 User Message；历史 Run 记录实际失败模型，Researcher 可在新 Run 中重试或选择另一个 Catalog 项。
- [x] Agent Run 固定限制 Message Bytes、Context Tokens、Output Tokens、Tool Result Bytes、Tool Steps 和 Wall Time；超过限制在相应最早边界失败，不进行无限截断、无限 Tool Loop 或后台继续。
- [x] Step 或 Wall-time 终止只结束 Agent Run；已完成 Tool Outcome、A2UI 之前的持久内容及返回的 Core IDs 保留，已经 Admission 的 Core 工作不被 Cancel 或 Stop。
- [x] Auth Session 在新 Run 前失效、撤销或 Deactivate 时不交换 Token并显示登录状态；MCP Token 或 Scope 失败不降级为 Anonymous、旧 Token 或直接 Core API。
- [x] MCP `TEMPORARILY_UNAVAILABLE` 仅按 Tool Retry Guidance 和 Mastra 当前 Run Bounds 重试；不可重试错误、Admission Rejection 和 Formula Diagnostics 不被粗暴重试成重复 Mutation。
- [x] Registry 重启后移除历史 Thread 当前模型时保留旧 Run 标签，但下一次发送前要求选择 Enabled Model，不静默改为默认模型。
- [x] Title Generation、Usage Accounting 或非关键呈现失败不回滚已经成功的主 Agent Run；这些独立失败有明确状态且不伪造成功数据。
- [x] Scripted Providers 确定性覆盖 Timeout、Rate Limit、Bad Credential、Refusal、Malformed Event、Output Limit、Unexpected Error 及恢复路径；普通测试不访问公网或依赖 Provider 文案。
- [x] 浏览器测试验证 Error Copy、Retry、Model Change、无 Duplicate Message、已完成 Tool State 保留、Core Work 独立及键盘 Focus；断言行为而非错误的逐字长文本。
- [x] 失败测试输出安全 Trace ID、Run ID、Model Key、Reasoning、Step、Duration、Dependency Status、Seed 和退出码，为下一张 Telemetry Ticket 提供封闭 Metadata 输入。

## Verification and review

- Standards and Spec independently re-reviewed the identical staged patch
  `5ac87725a6b841e0a7286b951a33a628a695782ba4adc6b2bc47b6e055aca58c`
  from fixed base `677be3b76e038d3195d0857b0ba06d1ea01ba323`.
  Both axes report zero findings. Independent checks include Agent `124`,
  Web `57`, architecture `6`, and the real pinned CopilotKit/AG-UI late
  protocol-failure regression. This completion entry is the only post-review
  tracker change.
- Final `pnpm test` passed Ruff, Python `917`, Agent `351`, Auth `163`,
  Web `200`, and all typechecks. Agent PostgreSQL integration passed all
  `50` cases in isolated project `20260830t235025z-64353-aba6c2ed`.
  HTTP checks include the hard-cut `AGENT_LIMIT` response for a 16 KiB
  violation, historical model identity, closed terminal codes, duplicate
  admission, retained Tool outcomes, and noncritical invalid usage.
- Final Production Image run `20260830t235606z-67198-9ddb2d23` passed all
  `14` selected browser scenarios: seven provider faults and explicit
  recovery, Core work continuing after provider failure, missing login,
  Auth exchange timeout, a real MCP response disconnect, first Chat/reload,
  the large narrow-screen A2UI table, and Research/DailyTrack survival after
  Chat deletion. Explicit retries create distinct Run/User Message identities;
  reload never resubmits and a changed next model does not relabel history.
- Review and browser failures were fixed at their boundaries: invalid usage
  numbers no longer trigger limits; mobile historical model labels remain
  visible and recovery targets are at least 44 px; a private CopilotKit proxy
  mounts after runtime discovery; both received success and failure terminals
  survive a subsequent connection rejection. Four completed-history browser
  assertions now require `Run complete`, not a reset to `Ready`.
- The final mobile failure and retained-research screenshots were inspected.
  The final bundle contains `11` assets / `1,662,439` total bytes /
  `1,587,584` JavaScript bytes. The harness reports exit `0`, runtime
  secret cleanup `0`, and environment cleanup `0`. Failed test
  environments and their isolated volumes were also cleaned; reports remain.
- Infrastructure follow-up for Issue 13: attempt
  `20260830t233013z-48969-b20b3fda` stopped before any browser test when
  RustFS returned HTTP 404 to CreateBucket despite a healthy container.
  The original response metadata was insufficient to attribute the cause.
  Two fresh isolated S3 probes with the exact bucket name and subsequent
  image initializations succeeded without adding retries. This is not a
  claimed fix; retain the failed evidence and investigate/close the startup
  reliability risk in the final release gate. Other earlier failed image
  attempts are likewise not counted as passing acceptance.
