# 11 — Content-free telemetry and runtime isolation

**What to build:** 让 Operator 能测量 Agent 的可靠性、成本和失败类别，同时用封闭 Metadata Allowlist 和真实权限隔离证明 User/Assistant 内容、A2UI、Formula、MCP Payload、Cookie、Token 与 Provider Secret 不会进入日志、Trace、Health 或其他运行时 Authority。

**Blocked by:** 06 — Validated A2UI research surfaces; 10 — Bounded Agent failures and explicit retry

**Status:** ready-for-agent

- [ ] Agent Host 只发出封闭字段集合：Pseudonymous Researcher Correlation、Thread ID、Run ID、Trace ID、Model Key、Provider Model ID、Reasoning Effort、Token Usage、Step Count、Duration、Status、Retry Classification 和 Sanitized Error Category。
- [ ] User/Assistant Messages、System Instructions、Model Request/Response Body、Mastra Memory、A2UI Payload、Formula、Hypothesis、MCP Arguments/Results、Cookie、OAuth Token、Provider Credential、SQL、Path 和 Storage Record 不进入日志或 Trace。
- [ ] 用唯一 Canary 分别注入 User Message、Assistant Output、System Instruction、Formula、Hypothesis、A2UI、MCP Argument、MCP Result、Cookie、Access Token、Provider Key、Provider Error 与文件路径，并扫描 Agent、Auth、Core、Caddy、Worker 及测试诊断。
- [ ] 正常成功、Provider Failure、Auth Failure、MCP Error、Invalid A2UI、Agent Limit、Restart 和 Delete 的日志都通过 Canary 扫描；未知异常被净化为稳定类别，不输出 Stack Trace 中的私有值。
- [ ] Caddy 日志继续删除完整 URL、Query、Cookie、Headers、Body 和 Response Headers，只保留受控 Method、归一化 Route、Status、Request ID 与 Timing；Agent Streaming 不改变该边界。
- [ ] Liveness、Readiness、Startup Failure 和 Production Smoke Evidence 不返回 Registry Secret、Database URL、Issuer Key、Cookie、Token、Prompt、Tool Payload 或 Chat Content。
- [ ] Agent Runtime Role 只能访问 Agent Schema；真实 PostgreSQL 测试证明它不能读取 Auth/Core Schema，Core/Auth Runtime Role 也不能读取 Agent Chat Content。
- [ ] Agent Host 容器没有 Core/Auth Database URL、RustFS Key、Canonical Data Mount、Worker Queue Credential 或 Auth Signing Secret；Browser Bundle 没有 Provider 或 MCP Credential。
- [ ] Auth 是唯一 Token Signing Authority，Core 是唯一 MCP Resource/Ownership Authority，Agent Store 是唯一 Chat Content Authority；Telemetry 不新增 Agent Audit、Recovery、Transcript 或 Business State 表。
- [ ] Session Delete 后不存在依赖日志或 Trace 恢复 Chat 的路径；Core Research 保持独立，Telemetry 中的 opaque correlation 不能成为 Join 或 Cascade Key。
- [ ] 观察性测试同时证明必需 Metadata 在成功和失败 Run 中完整、单位和状态稳定，使后续 Eval 可计算 Usage、Duration、Tool Error 与 Failure Rate，而无需读取内容。
- [ ] 架构、真实权限、日志 Canary 和 Error-path 测试进入普通确定性 Gate；失败保留被净化的文件名/服务名与命中类别，但不回显 Canary 本身。
