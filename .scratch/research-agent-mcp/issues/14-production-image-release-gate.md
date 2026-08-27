# 14 — 通过最终 Production Image 与 release gate

**What to build:** 证明最终 Production Image 包含并能运行与源码测试相同的 MCP 实现，在隔离真实依赖中同时通过健康检查、OAuth Streamable HTTP、stdio、effectful Worker 链路和语义结果读取，然后通过项目完整 release gate。

**Blocked by:** 13 — 通过真实 Codex stdio 验收

**Status:** ready-for-agent

## Plan

1. 在只读挂载的验收脚本中提供显式本地 OAuth verifier，并让 image-smoke 的 API 容器通过正式 `create_app` 工厂挂载 `/mcp`；同时从镜像内证明默认生产入口在未提供 verifier 时仍不暴露 MCP。
2. 扩展 production-image smoke，在同一隔离 Compose project 中验证受保护资源元数据、scope-filtered discovery、read、effectful ResearchRun submission、API/MCP lifespan 重启、真实 Worker 终态与 bounded semantic Result。
3. 从最终 backend image 直接运行打包的 stdio entrypoint，验证初始化、精确 15 Tool、上下文读取、协议退出和 stdout 纯净，并断言锁文件中的官方 MCP SDK 版本与镜像安装版本一致。
4. 将 legacy/alias/通用执行面、MCP 专属持久化状态、超时轮询、净化协议证据、trace IDs、镜像 digest、随机种子、退出码和清理结果纳入自动验收及架构回归。
5. 先通过受影响的确定性测试和 image smoke，再完成双重 review/fix/re-review；实现提交后，从已提交 HEAD 执行完整 `pnpm check:release`，最后以独立 tracker 提交关闭本票。

- [ ] 最终镜像包含锁定版本的官方 MCP SDK、Core API MCP mount 和正式 stdio entrypoint，不依赖源码 checkout 或开发环境隐式包。
- [ ] image smoke 在独立的 PostgreSQL、RustFS、网络、volume、账号和 Fixture data 中启动，并验证初始化、健康检查、父/MCP lifespan、优雅停机与资源清理。
- [ ] 使用显式本地测试 OAuth verifier 验证 `/mcp` protected-resource 行为、scope-filtered discovery、一个 read flow、一个 effectful submission、断线重连和 Result 读取；没有 production verifier 时保持 fail-closed。
- [ ] 从镜像运行 stdio entrypoint，验证初始化、默认 15 个安全 Tool、上下文读取和协议退出，无 stdout 污染。
- [ ] effectful smoke 经过真实 Worker 到达终态，并通过 bounded semantic Result Tool 读取结果；transport/session 重启不丢失 durable resource。
- [ ] smoke 同时验证不存在 legacy SSE、aliases、compatibility/fallback、Data Operator 或通用执行 Tool，也不存在 MCP 专属 User/session/audit/idempotency state。
- [ ] 所有等待使用有 timeout 的条件轮询，失败自动保存容器日志、health、经净化的协议请求响应、trace ID、退出码、镜像 digest 和随机种子。
- [ ] 完整本地 release gate 在最终镜像与已提交实现上通过；任何 flaky、重跑后才通过或源码通过但镜像失败都阻止完成。
- [ ] 本票只形成可部署证据，不执行公共 Cloudflare 部署、DNS 变更或真实生产 OAuth provider 配置。
