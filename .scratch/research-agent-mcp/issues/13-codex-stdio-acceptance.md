# 13 — 通过真实 Codex stdio 验收

**What to build:** 让唯一要求的真实 Host——Codex——通过默认安全的 stdio MCP 配置，在 Fixture 数据上完成一次从研究上下文、Formula 诊断、ResearchRun 提交、durable polling 到分页结果解释的真实闭环，并留下可复查的验收证据。

**Blocked by:** 12 — 证明确定性 Agent 任务轨迹

**Status:** ready-for-agent

- [ ] 使用正式打包的 stdio entrypoint 配置真实 Codex，不调用内部 Python API、产品 HTTP route 或测试专用 bypass。
- [ ] 默认 `local_operator` discovery 精确显示 15 个安全 Tool，`cancel_research_run`、`cancel_research_batch`、`stop_daily_track` 不可见；不存在额外或 legacy Tool。
- [ ] Codex 调用 `get_research_context` 与 Alpha authoring Tool，生成或修正一条 Formula，并提交至少一个完整 ResearchRun。
- [ ] Codex 依据 durable `run_id` 和 polling guidance 等待真实 Worker 终态，MCP 进程重连后仍能继续查询同一资源。
- [ ] Codex 通过有界 Result section 和至少一次 cursor pagination 读取并总结产品语义结果，而不接触 manifest、object key、checkpoint、SQL 或路径。
- [ ] 验收使用隔离 Fixture 数据与真实 PostgreSQL、RustFS、Worker，不依赖公网数据、真实 OAuth provider 或第二个 MCP Host。
- [ ] 证据记录 Host 配置摘要、discovered Tool names、durable IDs、状态轨迹、分页边界、最终结论、trace IDs 和版本信息，同时遵守 Formula、hypothesis、token、positions 等日志脱敏规则。
- [ ] 若真实 Codex 行为暴露 Tool description/Schema 歧义，先修正公共合同并重跑确定性测试，再重新完成真实 Host 验收；不得用 prompt workaround 或兼容 alias 掩盖问题。
- [ ] 验收通过后仍不启用公共 Cloudflare 部署，也不声称第二 Host 或生产 OAuth 已验证。
