# 09 — Same-session concurrency and restart recovery

**What to build:** 让同一 Researcher 在两个浏览器或设备打开同一个 Chat Session 时看到同一 Agent Run，并由 CopilotKit AgentRunner 保持一个 Thread 只有一个活动 Run；断线、重连和 Agent Host 重启不会重复提交 Message，已经进入 Core 的工作继续独立运行。

**Blocked by:** 04 — Idea-to-ResearchRun loop; 05 — Session history and independent deletion

**Status:** complete

## Implementation plan

1. Verify the pinned CopilotKit Runner and AG-UI client contracts in their
   installed source. Keep native `onConcurrentRun: throw` admission and durable
   Mastra history; do not introduce a queue, lease, interrupt endpoint, account
   lock, or resumable model job. Preserve the exact accepted Thread/Run IDs.
2. Synchronize an already-open idle Chat with changes made by another client.
   Observe only the selected Session's authenticated, bounded metadata request;
   reconnect through AG-UI when its activity/running state changes. Never
   resubmit a user message, open overlapping client streams, or convert this UI
   observation into a Core Research watcher. Dispose requests on navigation.
3. Extend real PostgreSQL HTTP/AG-UI tests using controlled Scripted Tool
   barriers: one Thread rejects a competing Run without new persisted content,
   different Threads run independently, disconnected readers reattach to the
   same Run, deletion stays blocked, and foreign/unknown identities share the
   same Not Found boundary. Cover connection/persistence races explicitly.
4. Make Host shutdown terminate unfinished model execution through the existing
   framework lifecycle before closing storage. Persist completed Messages and
   Tool outcomes, mark interrupted invocation failed, and replay it after
   restart without silently resuming. Core admission/Worker state is untouched.
5. Add bounded test-only barriers to the existing isolated MCP fault proxy and
   final-image browser tests with two independent authenticated contexts. Prove
   idle-to-running/terminal synchronization, Composer disabling, direct native
   rejection, reconnect without duplicate Message/effect, parallel Sessions,
   and Worker completion after Agent restart. Save sanitized identity/order and
   dependency evidence; use condition polling, never arbitrary sleeps.
6. Run affected deterministic, real PostgreSQL, and final-image browser gates.
   Obtain independent Standards and Spec reviews of the same staged SHA256,
   repair and re-review any findings, then close this tracker and commit Issue
   09 alone before beginning Issue 10.

- [x] 两个已认证浏览器上下文打开同一 opaque Session ID 时读取同一 Thread、Messages、当前 Run ID 和 Terminal History，而不是创建客户端本地副本。
- [x] 第一个客户端开始一个由 Barrier 控制的长 Scripted Run 后，第二个客户端能观察 Running State；Composer 在两端禁用且不会发送重叠 Turn。
- [x] 绕过 UI 直接提交第二个同 Thread Run 时使用 AgentRunner 的支持行为明确拒绝或绑定现有 Run，不产生第二个 User Message、模型调用、Tool Call 或自定义 `session_busy` Product State。
- [x] 不同 Chat Sessions 可以并行运行，只有 AgentRunner 和固定 Deployment Capacity 限制它们；不存在全账号单 Run 锁或持久自定义 Queue。
- [x] AG-UI Stream 中断后重新打开 Session 会以相同 Run Identity 重放已经持久的 Event 和 Message，不自动重发最后一条 User Message，也不重复已完成的 MCP Mutation。
- [x] Agent Host 在至少一个 Tool Outcome 完成后重启时，Thread、Messages、完成的 Tool Outcome 和 Core IDs 保持可见；未完成的 Model Invocation 进入明确 Terminal Failure，而不是静默继续或切换模型。
- [x] 如果重启或 Wall-time 发生在 Core 接受 ResearchRun 之后，真实 Worker 继续到终态；后续 Agent Run 能通过保留的 ID 或授权 List Tool 再次读取并解释结果。
- [x] Active Run 期间不允许 Session Delete，且删除不作为 Interrupt；Run 终态后按 Session Ticket 的独立删除契约工作。
- [x] Cross-Researcher Client 无法 Attach、Observe、Resume 或判断另一 Researcher 的 Run 是否存在；所有结果与 Unknown Session 一致为 Not Found。
- [x] 并发、重连和重启测试使用固定 Clock、UUID、Seed、Barrier 与有 Timeout 的条件轮询，不使用任意 Sleep；失败保存安全 Event Order、Run ID、Dependency State 和进程退出证据。
- [x] 真实浏览器验收覆盖两个 Context 的 Running/Terminal 可见性、Composer 状态、重连和不同 Session 并发，同时证明只有一个有序 Turn 被持久化。

## Verification and review

- Standards and Spec independently re-reviewed staged patch
  `d6ff8896e98a53de7f78a30d128098733bf7b1ce96e130cda17a1f390694406c`
  from fixed base `c97eced356affcd5cb60156905d88e2c7f6debd0`.
  Both axes report zero findings. Independent checks passed Agent `16`, Web
  `49`, architecture `6`, and typechecking. This completion entry is the only
  post-review tracker change.
- Final deterministic baseline passed Ruff, Python `917`, Agent `298`, Auth
  `163`, Web `166`, and all typechecks. Agent PostgreSQL integration passed
  `39` cases covering native concurrent rejection, parallel Sessions, active
  deletion, foreign/unknown identity equivalence, durable replay, and shutdown
  after completed Tool outcomes. The bridge drains before closing its pool.
- Exact final Production Image run `20260830t221846z-11425-adb841ac` passed all
  `3` selected browser scenarios: shared Session/two contexts with a parallel
  Session; Host restart after Core admission; and first-message/rename/New Chat/
  back-forward/reload regression. Safe database attachments assert one ordered
  User Message per accepted Turn and no extra Core admission after restart.
  The independent real Research Worker finishes the retained ResearchRun, and
  an explicit later message reads its Result through MCP.
- Native Mastra MCP signal handling uses `exit-hook`; the Host joins that
  awaited lifecycle. A successful SIGTERM shutdown preserves exit code `143`
  and emits `agent_shutdown_completed` after model, Memory, database and HTTP
  drain. Tests assert both facts, not merely that the container stopped.
- Earlier image attempts exposed two real defects: leftover HTTP stream
  connections blocked shutdown after runtime drain, and a new Thread inherited
  the previous Thread's accepted state for its first render. These were fixed
  at their lifecycle/identity boundaries and verified in the final image;
  temporary diagnostic markers were removed. Failed attempts are not counted
  as passing evidence.
- The final shared-Session Running screenshot was inspected. Both contexts
  expose the same Run identity and disabled Composer, with the current Session
  marked Running. The final Web bundle contains `11` assets / `1,653,468` total
  bytes / `1,578,878` JavaScript bytes. The harness reports exit `0`, runtime
  secret cleanup `0`, and cleanup `0`; development data was untouched.
