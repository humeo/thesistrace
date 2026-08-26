# 02 — 提供 OAuth 保护的 Streamable HTTP 只读闭环

**What to build:** 让远程 MCP 客户端通过 Core 进程内唯一的 `/mcp` 端点，在本地确定性 OAuth issuer 的保护下发现并调用已存在的研究上下文 Tool；连接可以断开和重建，业务能力、授权和结果仍由同一个 Capability Registry 与 Core 决定。

**Blocked by:** 01 — 建立安全的 stdio Research Agent 上下文闭环

**Status:** ready-for-agent

- [ ] 将 stateless Streamable HTTP MCP 应用挂载到现有 Core ASGI 进程，并由父应用 lifespan 显式管理 MCP session manager；不得创建第二套 Core runtime、数据库连接 authority 或域服务。
- [ ] HTTP 仅暴露一个 `/mcp` 端点，不存在 legacy HTTP-plus-SSE、版本化 MCP 端点、兼容 alias 或自定义 Tool-set header。
- [ ] 确定性测试 OAuth issuer 可签发短期 bearer token，并验证 issuer、audience、signature、expiry、not-before 和 scopes；整个测试不依赖公网或真实账号。
- [ ] Tool discovery 是 deployment allowlist 与已认证 grant 的交集，Tool invocation 会再次检查 scope；无 token、畸形 token、失效 token、错误 issuer/audience/signature 均失败关闭且不会降级成匿名 principal。
- [ ] 生产 HTTP auth adapter 缺少真实 verifier/provider 时应用构造失败；不存在 `AUTH_DISABLED`、query token、可信自定义 scope header 或失败认证 fallback。
- [ ] 未受信任的 Host/Origin 被拒绝，受信任部署值有确定性契约测试，以保留 Streamable HTTP 的 DNS rebinding 防护。
- [ ] 相同的三个上下文 Tool 通过 HTTP 返回与 stdio 相同的 structured content、输出 Schema、错误语义和 scope 行为。
- [ ] 客户端断线并重新初始化后可以再次读取上下文；MCP transport/session 不保存或恢复任何 Product State。
- [ ] ASGI 集成、OAuth 负向路径、scope-filtered discovery、调用重授权、断线重连和优雅停机测试通过，并保留经净化的诊断证据。
