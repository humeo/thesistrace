# ThesisTrace 独立 Research Agent Host 框架比较

Date checked: 2026-08-29

## 研究边界

本文只使用各项目的官方文档、官方仓库当前 `main` 源码和官方包元数据，比较
Agno、Mastra 与原 `badlogic/pi-mono` 对 ThesisTrace 独立 Research Agent Host
的适配性。后者现已重定向到 [`earendil-works/pi`](https://github.com/badlogic/pi-mono)，
包名也已变为 `@earendil-works/*`；本文比较当前的 `pi-agent-core` 和
`pi-coding-agent`，不以旧教程或第三方扩展为依据。

本项目已有的边界是前提，而不是交给框架重新定义：Core 内的 MCP 是无状态
Streamable HTTP `/mcp`，MCP 不拥有 User、Tenant、ResearchRun、Research Batch
或 DailyTrack 等业务状态，连接关闭后仍以 Core 的持久状态为恢复事实
（当时的 V1 MCP 契约）；远程 MCP 是 OAuth 2.1
protected resource，只接受请求上下文中的 access token
（[ADR-0221](../adr/0221-authenticate-remote-research-agent-access-with-oauth.md)）；
HTTP MCP 继续挂在 Core FastAPI/ASGI 进程中
（[ADR-0220](../adr/0220-expose-research-agent-access-through-a-native-core-mcp-adapter.md)）。

因此正确的数据流是：

`Web UI -> 独立 Agent Host（MCP client） -> Core /mcp -> Core services/workers`

方向上，“加一个独立 Agent，让它使用现有 MCP”是对的；但 Agent Host 还必须
负责模型循环、Web 流式协议、对话会话、OAuth token 转发/刷新、工具审批、
结构化最终产物、审计和评测。通常不应由 Agent Host 再代理或重新暴露一套 MCP。

## 结论先行

1. **首选 Mastra。** 它是三者中唯一同时提供一等 Streamable HTTP MCP client、
   请求级动态鉴权转发、MCP OAuth provider/token 刷新与持久化接口、工具审批的
   候选，最贴合 ThesisTrace 当前远程 `/mcp` 契约。TypeScript Host 与 Python
   Core 之间只通过 HTTP/MCP 通信，不构成语言耦合。
2. **Agno 是明确的第二选择。** 如果团队坚持 Python/FastAPI，且 ThesisTrace
   已能在每次 Agent run 前取得有效 Bearer token，Agno 的 `header_provider`、
   AgentOS、AG-UI、Pydantic output 和数据库会话足够成熟。主要缺口是 Agno 当前
   MCP 公共接口没有 Mastra 那样完整的 OAuth 授权流程和 token storage 抽象。
3. **Pi 暂不用于 V1 产品 Host。** `pi-agent-core` 是很干净的可嵌入 agent loop，
   但当前上游没有一等 MCP client；Web server 仍是 experimental，结构化输出、
   MCP OAuth、产品会话、exporter 和部署都要自行组装。它的“薄”会转化为本项目
   最大的自建面积。
4. **若选 Pi，只选 `pi-agent-core`，不要以 `pi-coding-agent` 作为产品 Host。**
   后者是终端 coding harness，默认工具包含 read/bash/edit/write；ThesisTrace 的
   Agent 应只有经过授权的 MCP tools 和少量纯内部展示/审批工具。

## 能力对比

| 维度 | Mastra | Agno | Pi |
| --- | --- | --- | --- |
| 语言与运行时 | TypeScript；官方部署文档支持 Node.js 22.13+、Bun、Deno、Cloudflare，可用独立 Hono server 或嵌入现有 Web framework（[Deploy](https://mastra.ai/docs/deployment/overview)）。 | Python；当前 PyPI `agno 3.0.1` 要求 Python 3.9–3.13，并提供 `mcp`、`os`、`opentelemetry` 等 extras（[PyPI](https://pypi.org/project/agno/)）。 | TypeScript ESM；当前 `pi-agent-core` 包要求 Node.js 22.19+（[package.json](https://github.com/earendil-works/pi/blob/main/packages/agent/package.json)）。 |
| Streamable HTTP MCP | `MCPClient` 对 URL 先尝试 Streamable HTTP；可传 `requestInit`、自定义 `fetch`、host allowlist、timeout 和 protocol version（[MCPClient](https://mastra.ai/reference/tools/mcp-client)）。 | `MCPTools` 原生支持 `streamable-http`，`StreamableHTTPClientParams` 包含 headers、timeout、SSE read timeout 和 close 行为（[文档](https://docs.agno.com/tools/mcp/transports/streamable_http)、[参数源码](https://github.com/agno-agi/agno/blob/main/libs/agno/agno/tools/mcp/params.py)）。 | 截至检查日，官方包清单和 `pi-agent-core` 依赖中没有 MCP client；`pi-coding-agent` 仅把 “MCP server integration” 列为可由 extension 实现的能力（[仓库](https://github.com/earendil-works/pi)、[coding-agent README](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/README.md)）。需自行桥接官方 MCP TypeScript SDK。 |
| OAuth / 动态 headers | 自定义 `fetch(url, init, requestContext)` 可逐请求转发 Bearer token；`authProvider` 支持自动刷新和 OAuth 流程，`OAuthStorage` 可按用户持久化 token，已有 token 也可用 simple provider（[MCPClient](https://mastra.ai/reference/tools/mcp-client)）。内置 loopback callback 只适合本地；产品 HTTPS redirect 仍要由 Host 提供 callback endpoint。 | `header_provider` 每个 run 都能读取 `RunContext` 并生成 Authorization/header，且初始化 discovery 也会带 headers（[Dynamic Headers](https://docs.agno.com/tools/mcp/dynamic-headers)、[源码](https://github.com/agno-agi/agno/blob/main/libs/agno/agno/tools/mcp/mcp.py)）。当前公开构造参数和 HTTP 参数源码未见 OAuth provider、授权回调或 token storage；完整 OAuth 生命周期需应用层实现。 | Pi 文档中的 OAuth 是模型 provider 登录，不是 MCP OAuth（[Providers](https://pi.dev/docs/latest/providers)）。由于没有一等 MCP client，MCP Bearer 转发、401 challenge、refresh 和 token storage 都由应用层负责。 |
| 工具审批与安全边界 | MCP server 可整体或按 `toolName/args/requestContext` 动态要求审批；另有 `allowedHosts` 防 SSRF，官方也明确 MCP annotations 不能作为可信授权边界（[MCPClient security/approval](https://mastra.ai/reference/tools/mcp-client)）。 | AgentOS 提供 human-in-the-loop/approval，Agent 本身支持暂停与继续；但 MCP headers 和业务授权仍应在 Core 逐次执法（[AgentOS introduction](https://docs.agno.com/agent-os/introduction)、[Running Agents](https://docs.agno.com/agents/running-agents)）。 | Core 有 `beforeToolCall`/`afterToolCall` hook，可拦截或终止工具；但项目 README 明确 Pi 没有内建 filesystem/process/network/credential permission system（[agent-core](https://github.com/earendil-works/pi/tree/main/packages/agent)、[仓库安全说明](https://github.com/earendil-works/pi#permissions--containerization)）。 |
| Web 流式集成 | Agent stream 同时提供 text chunks 和 start/text-delta/tool-call/tool-result/finish 等事件，并可转换为 AI SDK v5 stream，适合现有 React Web UI（[Streaming](https://mastra.ai/docs/guides/streaming)）。 | AgentOS 提供 50+ production API 与 SSE 流式能力；AG-UI 直接挂 FastAPI router，`POST /agui` 流出标准事件和自定义 tool events（[AgentOS](https://docs.agno.com/agent-os/introduction)、[AG-UI](https://docs.agno.com/agent-os/interfaces/ag-ui/introduction)）。 | `pi-agent-core` 的 `agent_start`、message delta、tool progress、`agent_end` 事件很适合自建 UI（[agent-core event flow](https://github.com/earendil-works/pi/tree/main/packages/agent)），但官方 `pi-server` 仍标为 experimental、只给 Unix preset，且要求应用自己实现 service、transport 与 auth；它不是现成 Web Host（[pi-server](https://github.com/earendil-works/pi/tree/main/packages/server)）。 |
| 会话与持久化 | Memory 用 `resource` 标识用户/实体、`thread` 隔离对话，并写入配置的 storage provider（[Memory](https://mastra.ai/docs/memory/overview)）。 | 给 Agent 配置 database 后会自动持久化 session、runs、metadata、summary，并以 `user_id/session_id` 隔离（[Session Storage](https://docs.agno.com/database/session-storage)）。 | coding-agent 默认以 JSONL tree 保存终端会话（[Sessions](https://pi.dev/docs/latest/sessions)）；agent-core 另有 SQLite repository/migrations/FTS 包（[SQLite backend](https://github.com/earendil-works/pi/tree/main/packages/session-backends/sqlite-node)），但产品级用户归属、租户隔离和 Web session API 仍需设计。 |
| 结构化输出 | `structuredOutput` 接受标准 JSON Schema，支持独立 structuring model 和 strict/warn/fallback 校验策略，返回经 schema 验证的 object（[Agent.generate](https://mastra.ai/reference/agents/generate)）。ThesisTrace 应使用 `strict`，不使用 fallback。 | `output_schema` 接受 Pydantic/JSON Schema；可和工具调用共存，最终返回已验证 Pydantic 对象（[Structured Output](https://docs.agno.com/input-output/structured-output/agent)）。 | 没有同等级 Agent output-schema API；官方示例用 TypeBox 定义一个 `terminate: true` 的最终工具承载机器可读结果（[structured-output example](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/examples/extensions/structured-output.ts)）。模式可用，但需要自己定义最终产物协议。 |
| 测试与 Eval | Evals 支持 rule/model/statistical scorers、CI、live scoring、multi-turn；gates/verdicts 可断言工具调用和硬条件（[Evals](https://mastra.ai/docs/evals/overview)、[Gates](https://mastra.ai/docs/evals/gates-and-verdicts)）。 | 官方 Eval 覆盖 accuracy、agent-as-judge、performance、reliability；reliability 可检查预期工具调用和错误处理（[Evals](https://docs.agno.com/evals/overview)、[Reliability](https://docs.agno.com/evals/reliability/overview)）。 | 仓库内 eval harness 能以 `vitest-evals` 做隔离项目、重复运行、baseline/candidate、token/latency/cost 比较（[README](https://github.com/earendil-works/pi/tree/main/packages/evals)），但其包元数据是 `private: true`，不是已发布的稳定产品 API（[package.json](https://github.com/earendil-works/pi/blob/main/packages/evals/package.json)）。 |
| Observability | 自动 trace agent、LLM、tool、memory 和 workflow，并可连接现有 OpenTelemetry parent trace（[Tracing](https://mastra.ai/docs/observability/tracing/overview)）。 | Agno Tracing 基于 OpenTelemetry，自动记录 Agent/model/tool/team/workflow，默认可存自有数据库并导出外部 OTel 平台（[Tracing](https://docs.agno.com/tracing/overview)）。 | `pi-telemetry` 只定义显式、vendor-neutral contracts、NOOP 和内存实现；官方明确不带 exporter 或 telemetry backend，应用需自己接 OTel/Sentry/logs adapter（[pi-telemetry](https://github.com/earendil-works/pi/tree/main/packages/telemetry)）。 |
| 部署与框架侵入性 | 可独立构建成 Hono server 并部署 VM/container/PaaS；功能面很宽，但可只采用 Agent + Memory + MCP + tracing，侵入性中等（[Mastra server](https://mastra.ai/docs/deployment/mastra-server)）。 | AgentOS 是完整 runtime/control plane，带 API、DB、RBAC、sessions、memory、traces 和 UI；Docker/PostgreSQL 模板可上任意支持 Docker 的云（[AgentOS](https://docs.agno.com/agent-os/introduction)、[Docker](https://docs.agno.com/deploy/templates/docker/deploy)）。开箱快，但最容易与 ThesisTrace 已有平台概念重叠。 | agent loop 最薄；但 `pi-server` 不提供 standalone CLI/coding-agent service，应用必须提供 service implementation（[pi-server](https://github.com/earendil-works/pi/tree/main/packages/server)）。框架侵入性最低，集成与运维自建量最高。 |

## 三个候选的具体判断

### Mastra：最适合当前 V1

Mastra 的决定性优势是它已经覆盖最容易出错的 Host 边界：逐请求凭证、OAuth
token 生命周期、动态 MCP toolset、审批、Web 事件、对话持久化、严格结构化输出
和 OTel trace。建议只使用一个 Research Agent，不引入 network、多 Agent、RAG 或
workflow；ResearchRun 的生命周期继续完全由 MCP/Core 驱动。

有两个必须显式处理的摩擦：

- `MCPClient` 对 URL 默认会在 Streamable HTTP 失败后尝试 legacy SSE
  （[官方参考](https://mastra.ai/reference/tools/mcp-client)）。ThesisTrace 不提供
  legacy SSE，验收测试应确认 Streamable HTTP 失败时整体 fail closed，不能把
  fallback 尝试当成成功路径。
- `authenticate()` 的内置 callback server 面向 loopback；生产 HTTPS OAuth
  callback 需要 Agent Host 自己暴露 endpoint，然后驱动同一个官方 provider
  （[OAuth callback/storage](https://mastra.ai/reference/tools/mcp-client)）。如果
  ThesisTrace Web 会话已经持有可用 access token，V1 更简单的做法是通过
  request-scoped custom `fetch` 转发，不在 Agent prompt、tool arguments 或模型
   history 中保存 token。

### Agno：Python 优先时可选

Agno 的 Web runtime、SSE/AG-UI、session DB、Pydantic output、tracing 和 evals 都
比 Pi 更接近成品。若 Agent Host 与 Core 运维团队希望统一 Python/FastAPI，它是
务实选择。建议使用最小 AgentOS + AG-UI/必要 API，不采用其完整平台模板中的
用户、知识库、Agent builder 等产品概念作为 ThesisTrace 的第二套权威模型。

选择 Agno 的前置条件应写清：Host 必须能在每个 run 前安全取得/刷新 Core MCP
access token，再由 `header_provider` 写入 Authorization header。若产品要求 Host
独立完成标准 MCP OAuth discovery、authorization callback、refresh 和按用户持久化，
则需要额外应用代码，Mastra 的适配成本更低。

### Pi：适合自研 Harness，不适合当前交付目标

`pi-agent-core` 的事件模型、可注入 `streamFn`、工具 hook 和独立 session backend
都很清晰，适合团队有意拥有整个 harness 时使用。问题是 ThesisTrace 现在需要的
并非一个更漂亮的 loop，而是可靠的 MCP/OAuth/Web/session 产品接缝；这些恰好是
Pi 当前没有打包好的部分。

`pi-coding-agent` 的 SDK 确实支持自定义 UI、RPC、custom tools 和 session manager
（[SDK](https://pi.dev/docs/latest/sdk)），但其默认系统、文件资源发现和 coding tools
会扩大权限面。即使未来选择 Pi，也应从 `pi-agent-core` 开始，仅注入允许的 MCP
tools，并自行实现薄 Web/Auth adapter，而不是裁剪一个终端 coding agent。

## 推荐的最小落地形态

首版采用独立 Mastra Host，但保持以下硬边界：

1. 一个 Research Agent；只装载当前用户授权下动态发现的 ThesisTrace MCP tools，
   不提供 shell、filesystem、通用 HTTP 或直接数据库工具。
2. Agent Host 只持久化 chat thread、展示事件、approval decision、OAuth token
   vault 和 trace correlation；ResearchRun/Batch/DailyTrack ID 与状态只引用 Core，
   不复制状态机。
3. 每次请求通过 `RequestContext` 选择用户 token 和 MCP toolset；token 不进入 prompt、
   message history、tool arguments 或 trace payload。
4. 最终回答使用 strict schema，例如 `AlphaProposal`：idea interpretation、formula、
   validation evidence、submitted run IDs、report summary、warnings；创建/取消/停止等
   side effect 继续由 MCP 工具返回的 canonical result 决定。
5. 工程测试使用 scripted/fake model 固定轨迹，分别覆盖 token 缺失/过期、401/403、
   tool discovery、审批/拒绝、断流重连、重复提交、取消与恢复；真实模型 Eval 另用
   固定 idea 数据集统计任务成功率、成本、P95 latency、工具错误率和多次运行方差。

最终排序：**Mastra > Agno > Pi**。只有在“统一 Python 运维”比“完整 MCP OAuth
client”更重要时改选 Agno；只有在团队明确决定长期自研 Agent Harness 时再考虑 Pi。
