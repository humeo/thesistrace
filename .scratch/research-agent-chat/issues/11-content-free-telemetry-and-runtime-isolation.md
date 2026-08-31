# 11 — Content-free telemetry and runtime isolation

**What to build:** 让 Operator 能测量 Agent 的可靠性、成本和失败类别，同时用封闭 Metadata Allowlist 和真实权限隔离证明 User/Assistant 内容、A2UI、Formula、MCP Payload、Cookie、Token 与 Provider Secret 不会进入日志、Trace、Health 或其他运行时 Authority。

**Blocked by:** 06 — Validated A2UI research surfaces; 10 — Bounded Agent failures and explicit retry

**Status:** complete

## Implementation plan

1. Reuse the current request-local Run observation and durable terminal seam.
   Emit structured metadata for accepted Runs, completed Tool operations and
   terminal Runs through one closed, value-validated writer. Correlate opaque
   Thread/Run/request identities and a pseudonymous Researcher value; never
   pass whole requests, errors, model objects, SQL or content to the writer.
   Logging failure must not alter the accepted Run or become recovery state.
2. Preserve the native silent Mastra/MCP logging configuration and disabled
   CopilotKit telemetry. Inspect the pinned bridge/runtime error boundaries
   for raw exception logging and test them with private-value canaries. Keep
   provider/system/Memory/A2UI/Tool content exclusively in existing stores;
   add no exporter, transcript, telemetry table, queue or business authority.
3. Make token counts a correctly bounded per-Run aggregate across provider
   steps; unknown or malformed counters stay explicitly unreported, never
   fabricated zero. Keep step count, duration units, status, retry category
   and safe failure categories consistent in successful and failed events.
4. Extend real PostgreSQL permission checks in both directions using the
   existing isolated roles, and verify final-container environment/mounts and
   browser assets without printing credential values. Exercise deletion and
   restart without a logging-based history or Research cascade.
5. Add deterministic end-to-end canary scenarios covering success, provider /
   Auth / MCP / A2UI failure, Agent limits, restart and deletion. Scan Agent,
   Auth, Core, Caddy, Workers and diagnostic artifacts before redaction so a
   leak fails the gate; preserve only sanitized service/category evidence.
   Reuse existing production-test fixtures, isolation and cleanup contracts.
6. Run unit/architecture, real database and isolated final-image canary gates.
   Obtain independent Standards and Spec reviews of one staged SHA256; fix
   and re-review, then update this tracker and commit Issue 11 alone before
   beginning Issue 12. The final release gate retains the Issue 10 RustFS
   startup reliability investigation.

- [x] Agent Host 只发出封闭字段集合：Pseudonymous Researcher Correlation、Thread ID、Run ID、Trace ID、Model Key、Provider Model ID、Reasoning Effort、Token Usage、Step Count、Duration、Status、Retry Classification 和 Sanitized Error Category。
- [x] User/Assistant Messages、System Instructions、Model Request/Response Body、Mastra Memory、A2UI Payload、Formula、Hypothesis、MCP Arguments/Results、Cookie、OAuth Token、Provider Credential、SQL、Path 和 Storage Record 不进入日志或 Trace。
- [x] 用唯一 Canary 分别注入 User Message、Assistant Output、System Instruction、Formula、Hypothesis、A2UI、MCP Argument、MCP Result、Cookie、Access Token、Provider Key、Provider Error 与文件路径，并扫描 Agent、Auth、Core、Caddy、Worker 及测试诊断。
- [x] 正常成功、Provider Failure、Auth Failure、MCP Error、Invalid A2UI、Agent Limit、Restart 和 Delete 的日志都通过 Canary 扫描；未知异常被净化为稳定类别，不输出 Stack Trace 中的私有值。
- [x] Caddy 日志继续删除完整 URL、Query、Cookie、Headers、Body 和 Response Headers，只保留受控 Method、归一化 Route、Status、Request ID 与 Timing；Agent Streaming 不改变该边界。
- [x] Liveness、Readiness、Startup Failure 和 Production Smoke Evidence 不返回 Registry Secret、Database URL、Issuer Key、Cookie、Token、Prompt、Tool Payload 或 Chat Content。
- [x] Agent Runtime Role 只能访问 Agent Schema；真实 PostgreSQL 测试证明它不能读取 Auth/Core Schema，Core/Auth Runtime Role 也不能读取 Agent Chat Content。
- [x] Agent Host 容器没有 Core/Auth Database URL、RustFS Key、Canonical Data Mount、Worker Queue Credential 或 Auth Signing Secret；Browser Bundle 没有 Provider 或 MCP Credential。
- [x] Auth 是唯一 Token Signing Authority，Core 是唯一 MCP Resource/Ownership Authority，Agent Store 是唯一 Chat Content Authority；Telemetry 不新增 Agent Audit、Recovery、Transcript 或 Business State 表。
- [x] Session Delete 后不存在依赖日志或 Trace 恢复 Chat 的路径；Core Research 保持独立，Telemetry 中的 opaque correlation 不能成为 Join 或 Cascade Key。
- [x] 观察性测试同时证明必需 Metadata 在成功和失败 Run 中完整、单位和状态稳定，使后续 Eval 可计算 Usage、Duration、Tool Error 与 Failure Rate，而无需读取内容。
- [x] 架构、真实权限、日志 Canary 和 Error-path 测试进入普通确定性 Gate；失败保留被净化的文件名/服务名与命中类别，但不回显 Canary 本身。

## Verification and review

- Standards and Spec independently completed the identical staged patch
  `95240a62d9ad678c3349ae8980922120d9dac29afe39cbf74bc5be6212ca7a1a`
  from base `cc14c720244da77dc7c071a6028f25ef7c8bdafd`, each with zero
  final findings. This completion entry and checked criteria are the only
  post-review tracker change.
- Final `pnpm test` passed Ruff, Python `929`, Agent `370`, Auth `163`,
  Web `200`, and all typechecks. Real Agent PostgreSQL integration passed
  `52` cases in isolated project `20260831t004618z-8987-31f34b13`,
  including existing Agent-to-Auth/Core denials and new reverse-role denials
  against existing Agent content.
- Final Production Image run `20260831t011004z-28688-27d88da3` passed all
  `9` selected browser scenarios, with zero unexpected, flaky or skipped
  cases. The privacy scenario covers all thirteen distinct canary categories
  across success, provider/Auth/MCP/A2UI failure, limits, restart and deletion.
  Original logs and diagnostics passed the pre-redaction scan; the final
  scanner also independently rechecked the retained HTML-embedded report.
  Secret cleanup, raw scan, environment cleanup and command exit are all zero.
- The real Agent image smoke passed in project
  `20260831t011008z-29169-45d2dbd5`, verifying startup, readiness, authenticated
  streaming, durable two-step usage, invalid startup and schema drift.
  Final-container checks prove no foreign database credentials or mounts,
  and every emitted browser asset is checked for provider/MCP credentials.
- Final E2E logs contain `21` accepted and `21` unique terminal Run
  observations with complete safe identity and measurement metadata.
  Usage is cumulative across model steps, missing counters remain unreported,
  and A2UI rejection is measured without failing otherwise successful work.
  Session deletion leaves zero owner Memory rows while the independent
  succeeded Core Research resource remains byte-for-byte unchanged.
- Review findings were reproduced before fixing: a real broken stderr pipe
  no longer terminates an accepted Run; HTML-embedded compressed diagnostics
  cannot evade scanning; malformed DEFLATE in either ZIP or HTML returns only
  a closed CLI error, never a raw stack. Native bridge error paths have five
  public-API regressions and a pinned, reproducible dual-build warning patch,
  with no protocol or execution change and no global console interception.
- An earlier PostgreSQL shutdown assertion was corrected to await the actual
  durable Memory commit before shutdown, rather than assuming a later Tool
  implies that commit. Failed verification attempts are not counted as passing;
  their isolated environments were cleaned. No development data was touched.
  The earlier Issue 10 RustFS startup reliability risk remains an explicit
  Issue 13 release investigation, not a claimed fix here.
