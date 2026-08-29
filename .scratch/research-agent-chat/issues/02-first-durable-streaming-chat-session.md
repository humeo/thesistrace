# 02 — First durable streaming Chat Session

**What to build:** 让 Researcher 在 New Chat 中提交第一条文本后创建一个真实、持久的 Agent Chat Session，并通过 CopilotKit React Core、AG-UI、CopilotKit Runtime、AgentRunner、Mastra Agent 和当前 Thread Memory 获得流式回复；刷新页面后重放同一 Session，而不是重新提交消息。

**Blocked by:** 01 — Authenticated Chat shell and model catalog

**Status:** complete

## Implementation Plan

1. Pin one reviewed, mutually compatible runtime cohort with no floating ranges:
   CopilotKit React Core and Runtime `1.69.3`, AG-UI Core/Client/Encoder
   `0.0.57`, `@ag-ui/mastra` `1.1.1`, Mastra Core `1.63.1`, Memory
   `1.28.1`, PostgreSQL Storage `1.22.1`, AI SDK runtime/provider contract
   `6.0.271`/`3.0.15`, and the matching OpenAI, Anthropic, and Google
   adapters. Use CopilotKit's `/v2` headless APIs and AG-UI as the only
   browser-Agent protocol; inspect the installed public types before wiring any
   boundary and add neither AI SDK UI nor a custom transcript stream.
2. Give the Agent Host its own fail-closed PostgreSQL boundary, following the
   repository's reviewed-schema pattern: a static Agent schema snapshot and
   catalog contract, an owner-only initializer that may install only an absent
   or empty schema, an `agent_runtime` role with only exact Agent-schema grants,
   and runtime startup verification with Mastra `PostgresStore({ disableInit:
   true })`. Keep Auth/Core database URLs and schema privileges out of the Agent
   runtime, and make any populated-but-nonexact schema a startup failure rather
   than migrating or falling back.
3. Make authenticated Researcher identity the Mastra resource identity on every
   request. Mount CopilotKit Runtime only after the existing same-origin Login
   Session check, construct the local Mastra adapter with that Researcher ID,
   and reject another Researcher's opaque Thread identifier as not found before
   history or execution can reach the framework store.
4. Implement New Chat as browser-only state. On the first bounded, nonblank text
   submission, accept one idempotent request that creates the opaque Thread
   ownership row and initial Run metadata atomically, then let Mastra persist the
   Thread/User Message and stream the Agent Run. Replace `/chat` with
   `/chat?session=<opaque-id>` through `history.replaceState` only after server
   acceptance; duplicate delivery reattaches/replays the same run rather than
   creating another Thread or User Message.
5. Define one deployed Mastra Research Agent whose `instructions`, selected
   registered provider model, mapped reasoning effort, and current-thread Memory
   are resolved at Run start. Disable semantic recall and working/global memory,
   use no prompt registry or planner, and persist the actual model key, provider
   model ID, reasoning effort, Agent build revision, usage, and terminal status
   for each Run without copying CopilotKit/Mastra's full state into product
   tables. A later selector change affects only the next Run.
6. Bind the existing project Chat components to `@copilotkit/react-core/v2` and
   the AG-UI lifecycle. Render persisted history, streaming assistant text,
   explicit running/complete/failed/disconnected states, and safe terminal
   errors directly from framework messages/events. Keep a text-only composer
   with a fixed 16 KiB UTF-8 payload limit, disable it while the current Thread
   runs, and expose no attachment or browser-authored run-state path.
7. Use CopilotKit's built-in in-memory AgentRunner for the basic one-active-run
   contract in this slice while PostgreSQL remains the authority for completed
   Thread/Message history and run metadata. Put only a thin `connect`/thread-
   endpoint adapter around that runner so an empty process can return a standard
   AG-UI `MESSAGES_SNAPSHOT` converted by Mastra's public message converter;
   it must delegate live Run ownership to the built-in runner and must not
   persist or infer another Run state. Do not add a queue, lease,
   `session_busy` state, resumable job table, cross-process coordinator, or
   browser retry state machine; the dedicated concurrency/recovery ticket will
   hard-cut that boundary later.
8. Add a Scripted Fake Model that implements the pinned AI SDK provider contract
   and deterministically emits chunks, usage, terminal failures, and replies.
   Cover the protocol and model metadata without network access, then use a real
   isolated Agent PostgreSQL for first creation, initializer/runtime schema
   behavior, transaction rollback, duplicate request idempotency, reload replay,
   completed-session restart replay, owner isolation/not-found behavior, and
   cleanup. Exercise the first-message and reload loop through Caddy in a real
   browser.
9. Run the smallest Agent/Web/schema suites first, then every repository gate
   affected by Compose, Auth, Caddy, and the browser flow. Review the completed
   diff serially against repository Standards and this ticket's Spec, fix every
   finding, re-run affected checks, re-review to zero findings, mark this ticket
   complete, and create one independent conventional commit containing only
   Issue 02.

- [x] 引入并精确锁定 CopilotKit React Core v2、CopilotKit Runtime、AG-UI、`@ag-ui/mastra`、Mastra、Provider Adapter 和 PostgreSQL Storage 的稳定版本；不得增加 AI SDK UI 或自定义平行流协议。
- [x] Agent Host 获得独立 PostgreSQL Schema、Initializer、Owner 和 Runtime Role；Runtime 只验证精确 Schema，不执行自动 Migration，也不能读取 Auth 或 Core Schema。
- [x] 未发送消息的 New Chat 只存在于浏览器状态；第一条合法文本被接受时才创建 Mastra Thread、持久 User Message 和 Agent Run，并将 URL 替换为该 Researcher 拥有的 opaque Session ID。
- [x] Agent 使用部署中的 Mastra `instructions`、用户选定的注册模型和推理强度、当前 Thread Memory 生成回复；不存在第二个 Prompt Registry、Prompt 表或 ThesisTrace Planner。
- [x] CopilotKit/AG-UI 流式传递 Run 开始、Assistant 内容、终态和安全错误；浏览器不根据纯 Token 文本反推 Agent 状态，也不维护第二套 Run 状态机。
- [x] 当前 Thread 的 User/Assistant Messages 和 Run Metadata 在真实 PostgreSQL 中持久化；刷新或重新打开 URL 会重放已有内容且不会再次执行模型。
- [x] 每个 Run 记录实际 Model Key、Provider Model ID、Reasoning Effort、Agent Build Revision、Token Usage 和 Terminal Status；改变 Thread 当前选择只影响下一次 Run。
- [x] Mastra 只接收当前 Thread Memory；跨 Thread Recall、全账号语义 Memory、Global Working Memory 和其他 Researcher 内容保持关闭。
- [x] 首版 Composer 只接受有上限的文本，不显示上传、图片、音频、代码文件或外部 URL 附件入口；消息过大在模型调用前得到明确错误。
- [x] 同一 Thread 的基本单活动 Run 约束由 AgentRunner 执行；此票不增加 Queue、Lease、`session_busy` Product State 或可恢复 Agent Job 表。
- [x] Scripted Fake Model 可完全确定事件和回复，使协议、持久化、重放及 Model Metadata 测试不访问公网或付费 Provider；真实模型调用不进入默认测试。
- [x] 使用真实 Agent PostgreSQL 覆盖首次创建、事务失败、重复请求、刷新重放、Agent Host 进程重启后的已完成 Session 读取、跨 Researcher Not Found 和清理隔离。

## Verification and Review

- Standards review from fixed base `f33d5a1` corrected active-Run payload
  conflicts and connect races, exact runtime-role validation, provider-usage
  redaction, fail-closed unknown Sessions, accessible payload-limit behavior,
  production telemetry defaults, and deployment documentation. Standards
  re-review: zero findings.
- Spec review corrected three remaining contract gaps: reconnect now preserves a
  safe terminal error when a Run fails before its own `RUN_STARTED`; persisted
  Thread model and reasoning preferences are restored without silent fallback;
  and failed Runs persist an explicit `{ reported: false }` usage value. All 12
  acceptance items above were rechecked. Spec re-review: zero findings.
- `env CI=true pnpm test`: Ruff passed; Python `877 passed`; Agent `61 passed`;
  Auth `143 passed`; Web `111 passed`; all TypeScript typechecks passed.
- `pnpm test:integration`: Core `370 passed, 8 deselected`; all six restart
  suites passed; Auth `84 passed`; Agent `12 passed`. Evidence:
  `.local/test-runs/20260829t201424z-36085-8d679971/evidence`.
- `pnpm test:e2e`: `19 passed`, including first stream, durable reload replay,
  opaque unknown-Session failure, 16 KiB enforcement, and model-preference
  restoration without a second model execution.
- Agent `pnpm test:image-smoke`, Web `pnpm build`, targeted architecture
  `37 passed`, and `git diff --check` all passed. Scripted Fake Model coverage
  required neither public network access nor a paid Provider.
