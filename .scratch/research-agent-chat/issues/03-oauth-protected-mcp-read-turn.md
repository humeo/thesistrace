# 03 — OAuth-protected MCP read turn

**What to build:** 让登录后的 Researcher 在 Chat 中询问当前可用数据与 Alpha 能力时，Agent Host 使用 Auth 签发的短期 Researcher OAuth Token 连接 Core 的 canonical `/mcp`，把实时发现的全部授权 Tools 交给 Mastra，并流式展示一次真实只读 Tool 调用。

**Blocked by:** 02 — First durable streaming Chat Session

**Status:** ready-for-agent

- [ ] Auth 新增私有 Login Session Exchange：每次先以数据库强制验证当前 Cookie 和 Active 状态，再签发以 Researcher ID 为 Subject、built-in Agent 为 Client、canonical `/mcp` 为 Audience 的短期 Access Token。
- [ ] Exchange Token 只包含部署批准的 `research:read`、`research:execute`、`tracking:read` 和 `tracking:execute`；不签发 `research:cancel` 或 `tracking:stop`，也不签发 Refresh Token。
- [ ] Auth 是唯一 Token 签发 Authority；Agent Host 不持有签名 Secret、不自行构造 Claim、不持久化 Access Token 或 Login Session Cookie，Core 使用对应的真实 Production Verifier。
- [ ] Token Lifetime 必须大于当前 Agent Run 最大 Wall Time 与 Clock-skew Margin 之和；关系不成立时相关服务启动失败，不在 Run 中增加 Refresh Token 或 Cookie 持久化方案。
- [ ] Core 的正式应用入口在完整 Production 配置下启用 `/mcp` 和 Protected Resource Metadata；缺少 Issuer、Audience、Verifier、Allowed Host、Allowed Origin 或 Deployment Policy 时启动失败。
- [ ] Caddy 精确代理 `/mcp` 及所需 Metadata 到 Core，同时继续阻止私有 Health/Internal 路径和 Query Token；Agent API 与通用 Core API 路由不吞掉 MCP 请求。
- [ ] 每个 Agent Run 重新验证 Login Session、交换 Token、建立 MCP Client 并执行 Tool Discovery；下一次 Run 会看到撤销 Session、Scope 或 Deployment Policy 变化。
- [ ] Agent Host 不包含 Core Tool 名称清单或 Host 级业务子集。Mastra 获得当前 Discovery 返回的每一个 Tool，并且每次调用仍由 Core 重做 Scope、Ownership 和资源状态检查。
- [ ] Approved Grant 的 Discovery 中所有当前 Read/Execute Tools 可见，所有 Cancel/Stop Tools 不可见；伪造旧 Discovery 后直接调用危险 Tool 仍由 Core 拒绝且不改变 Product State。
- [ ] 一个确定性 Chat Prompt 驱动 Scripted Fake Model 调用当前 Research Context 或 Alpha Catalog Tool，并把 Tool Name、Running/Terminal State、Safe Timing 与最终解释通过 AG-UI 展示。
- [ ] Cookie、OAuth Token、Claims、Provider Secret、Tool Arguments 和完整 Tool Result 不进入浏览器、Model Catalog、普通日志、错误正文或 Health 响应。
- [ ] 使用真实 Auth、Core、Agent Host 和隔离 PostgreSQL 验证成功读取，以及 Invalid/Expired/Revoked Session、Auth Timeout、Wrong Origin、Wrong Issuer/Audience/Subject/Client、Expired Token、Missing Scope、MCP Disconnect 和 Fail-closed Startup。
