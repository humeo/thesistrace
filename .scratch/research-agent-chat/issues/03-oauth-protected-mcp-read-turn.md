# 03 — OAuth-protected MCP read turn

**What to build:** 让登录后的 Researcher 在 Chat 中询问当前可用数据与 Alpha 能力时，Agent Host 使用 Auth 签发的短期 Researcher OAuth Token 连接 Core 的 canonical `/mcp`，把实时发现的全部授权 Tools 交给 Mastra，并流式展示一次真实只读 Tool 调用。

**Blocked by:** 02 — First durable streaming Chat Session

**Status:** complete

## Implementation Plan

1. Pin `@mastra/mcp` `1.17.2` into the existing Mastra cohort and use its
   reviewed Streamable HTTP client with protocol `2026-07-28` pinned exactly,
   an exact destination-host allowlist, bounded connect/discovery timeouts, and
   no legacy/SSE fallback. Keep Core's discovered names and schemas as the only
   business Tool inventory presented to Mastra.
2. Extend the Auth startup contract with one static Ed25519 signing key, its
   matching public JWK, an exact Issuer and canonical `/mcp` Audience, a stable
   built-in Agent client ID, a deployment-bounded grant drawn only from
   `research:read`, `research:execute`, `tracking:read`, and
   `tracking:execute`, and explicit token/run/skew durations. Reject malformed
   keys, dangerous or unknown scopes, duplicate scopes, and any lifetime that
   is not greater than the Agent Run wall-time plus clock-skew margin.
3. Configure Better Auth's JWT plugin with the static asymmetric key adapter
   and disabled response-header JWT behavior. Add only a private
   `POST /internal/session/exchange` adapter: it must force a fresh database
   Session lookup with cookie cache and refresh disabled, require an Active
   Researcher, then ask Better Auth to sign the exact short-lived access-token
   claims. It returns no Refresh Token and remains unreachable through Caddy.
4. Add a production Core token verifier and one exact MCP production-settings
   boundary. Verify the EdDSA signature, Issuer, string Audience, canonical
   Researcher UUID Subject, built-in client ID, integer temporal claims, JTI,
   expiry/not-before with the configured skew, and scope vocabulary before
   constructing the SDK `AccessToken`. Make the packaged and development Core
   entrypoints create the MCP-enabled application explicitly; missing verifier
   key, Issuer, Audience, client, allowed hosts/origins, or deployment Tool
   policy must fail startup instead of producing an Auth-disabled `/mcp`.
5. Route only `/mcp` and its exact OAuth Protected Resource Metadata path
   through Caddy before `/api/*`, reject MCP requests carrying any query string,
   preserve the existing private Health/Internal block, and pass no credential
   material to access logs. Wire Auth, Core, and Agent Compose services with the
   minimum asymmetric-key and MCP configuration each role needs: Auth receives
   the private key, Core receives only the public key, and Agent receives
   neither.
6. Add a private Agent token exchanger that forwards only the current request's
   Login Session Cookie to Auth and treats invalid/revoked Sessions, timeouts,
   non-200 responses, malformed payloads, and insufficient remaining lifetime
   as safe Run failures. For each newly accepted Run—never Catalog, connect, or
   duplicate replay—exchange once, create a uniquely identified MCP client,
   discover one complete Toolset with per-server errors preserved, reject
   partial/empty discovery, and install every returned Tool dynamically through
   Mastra's `RequestContext` without inspecting or listing Tool names.
7. Give the per-Run MCP client the same hard total wall-time as the Agent Run
   and close it on success, Tool/model failure, MCP disconnect, timeout,
   cancellation, subscriber disposal, and preparation failure. Keep the Cookie
   and opaque Access Token only in the request/client lifetime; do not place
   either in Mastra memory, PostgreSQL, model context, telemetry, or errors.
8. Preserve full Tool arguments/results only in server-side Mastra execution
   history while hardening the AG-UI boundary. Validate subsequent browser
   transcripts against a safe projection of authoritative server history, use
   authoritative history for the next model turn, suppress argument deltas and
   raw events, replace Tool results with bounded terminal markers, and sanitize
   live, duplicate, and reconnect snapshots. Render fixed CopilotKit/AG-UI Tool
   rows from standard Tool events/messages with only Tool name, running or
   terminal state, and locally measured safe duration.
9. Extend the Scripted Fake Model with a deterministic two-step trajectory: for
   the designated capability prompt it selects one currently supplied read Tool
   from the model call's discovered Tools, emits a valid Tool call, consumes the
   real Core result, and streams a bounded explanation. Keep the ordinary reply
   and failure modes deterministic and free of public network or paid Provider
   calls.
10. Cover Auth exchange/key/lifetime behavior, Core production verifier and
    startup failure, Caddy exact routing/query rejection, dynamic full discovery
    and dangerous-scope exclusion, stale dangerous direct calls, per-Run
    exchange/disconnect, AG-UI redaction/status/timing, and transcript replay
    with unit/contract tests. Then exercise real Auth, Core, Agent Host, isolated
    PostgreSQL, and Caddy for successful read plus every failure named by this
    ticket, including a real browser Tool turn.
11. Run the smallest affected suites first and then every repository gate for
    Auth, Core, Agent, Web, Compose, production images, and browser behavior.
    Review the fixed-base diff serially on repository Standards and ticket Spec,
    fix every finding, rerun affected acceptance, re-review to zero findings,
    mark only this ticket complete, and create one independent conventional
    commit containing Issue 03.

- [x] Auth 新增私有 Login Session Exchange：每次先以数据库强制验证当前 Cookie 和 Active 状态，再签发以 Researcher ID 为 Subject、built-in Agent 为 Client、canonical `/mcp` 为 Audience 的短期 Access Token。
- [x] Exchange Token 只包含部署批准的 `research:read`、`research:execute`、`tracking:read` 和 `tracking:execute`；不签发 `research:cancel` 或 `tracking:stop`，也不签发 Refresh Token。
- [x] Auth 是唯一 Token 签发 Authority；Agent Host 不持有签名 Secret、不自行构造 Claim、不持久化 Access Token 或 Login Session Cookie，Core 使用对应的真实 Production Verifier。
- [x] Token Lifetime 必须大于当前 Agent Run 最大 Wall Time 与 Clock-skew Margin 之和；关系不成立时相关服务启动失败，不在 Run 中增加 Refresh Token 或 Cookie 持久化方案。
- [x] Core 的正式应用入口在完整 Production 配置下启用 `/mcp` 和 Protected Resource Metadata；缺少 Issuer、Audience、Verifier、Allowed Host、Allowed Origin 或 Deployment Policy 时启动失败。
- [x] Caddy 精确代理 `/mcp` 及所需 Metadata 到 Core，同时继续阻止私有 Health/Internal 路径和 Query Token；Agent API 与通用 Core API 路由不吞掉 MCP 请求。
- [x] 每个 Agent Run 重新验证 Login Session、交换 Token、建立 MCP Client 并执行 Tool Discovery；下一次 Run 会看到撤销 Session、Scope 或 Deployment Policy 变化。
- [x] Agent Host 不包含 Core Tool 名称清单或 Host 级业务子集。Mastra 获得当前 Discovery 返回的每一个 Tool，并且每次调用仍由 Core 重做 Scope、Ownership 和资源状态检查。
- [x] Approved Grant 的 Discovery 中所有当前 Read/Execute Tools 可见，所有 Cancel/Stop Tools 不可见；伪造旧 Discovery 后直接调用危险 Tool 仍由 Core 拒绝且不改变 Product State。
- [x] 一个确定性 Chat Prompt 驱动 Scripted Fake Model 调用当前 Research Context 或 Alpha Catalog Tool，并把 Tool Name、Running/Terminal State、Safe Timing 与最终解释通过 AG-UI 展示。
- [x] Cookie、OAuth Token、Claims、Provider Secret、Tool Arguments 和完整 Tool Result 不进入浏览器、Model Catalog、普通日志、错误正文或 Health 响应。
- [x] 使用真实 Auth、Core、Agent Host 和隔离 PostgreSQL 验证成功读取，以及 Invalid/Expired/Revoked Session、Auth Timeout、Wrong Origin、Wrong Issuer/Audience/Subject/Client、Expired Token、Missing Scope、MCP Disconnect 和 Fail-closed Startup。

## Verification and Review

- Standards review closed durable accepted-message ordering, exact UTC replay,
  Core API-only MCP environment isolation, and deterministic browser exchange
  counting findings. Final Standards re-review from fixed base `0c58aca`: zero
  findings.
- Spec review closed exact Caddy query rejection, Ed25519 key-pair validation,
  Login Session Cookie minimization, real-service failure trajectories, and the
  final production-image MCP preflight environment contract. Final Spec
  re-review from fixed base `0c58aca`: zero findings.
- `pnpm test`: Ruff passed; Python `917 passed`; Agent `100 passed`; Auth
  `163 passed`; Web `112 passed`; all TypeScript typechecks passed.
- `pnpm test:integration`: Core `370 passed, 8 deselected`; all six restart
  suites passed; Auth `89 passed`; Agent `17 passed`. Evidence run:
  `20260830t020954z-9616-65bc00a1`.
- `pnpm test:e2e`: `23 passed`, including the real OAuth-protected Tool turn,
  browser projection redaction, reload/replay, Auth timeout recovery, MCP
  disconnect, and fail-closed session behavior. Evidence run:
  `20260830t020139z-86481-0b34a2f4`.
- `pnpm test:image-smoke`: Core, Auth, Agent, Web, and Caddy production images
  passed, including MCP preflight, HTTP restart/reconnect, stdio, readiness
  outages, non-root/runtime configuration, bounded evidence, and cleanup.
  Core evidence run: `20260830t023725z-22539-f08def64`.
- `git diff --check`: passed.
