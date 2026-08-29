# Cloudflare MCP 与 GitHub MCP Server 实现调研

Date: 2026-08-26

## 研究边界

本文只使用 Cloudflare、GitHub 自己维护的官方文档和官方仓库当前
`main` 源码。它是一份供 ThesisTrace MCP 设计使用的比较研究记录，不是
协议规范、实现计划或 ADR。

“Cloudflare MCP”需要拆成三层理解，否则很容易把示例框架和生产服务混在
一起：

1. Cloudflare Agents 文档给出的 Workers 上远程 MCP 托管方式；
2. [`cloudflare/mcp`](https://github.com/cloudflare/mcp) 中覆盖整个
   Cloudflare API 的 Code Mode 生产服务；
3. [`cloudflare/mcp-server-cloudflare`](https://github.com/cloudflare/mcp-server-cloudflare)
   中按产品域拆分的、强类型的生产服务。

GitHub 部分以 [`github/github-mcp-server`](https://github.com/github/github-mcp-server)
当前 `main`、仓库内官方文档和 GitHub Docs 为准。

## 结论先行

1. **两家的现行远程实现都选择无状态 Streamable HTTP。** Cloudflare
   当前明确要求新服务使用 `createMcpHandler()`，并把 `McpAgent` + Durable
   Objects 的会话式路径标为 deprecated；GitHub 的 HTTP handler 也明确设置
   `Stateless: true`。MCP 传输会话不是业务任务状态的存放处。
2. **Cloudflare 有两种互补的工具面。** 整个平台 API 用 `docs`、`search`、
   `execute` 三个工具压缩约 2,500 个端点；具体产品服务则保留少量、经过策划的
   typed tools。Code Mode 是解决超大 API 表面的手段，不是每个 MCP 服务的默认
   答案。
3. **GitHub 的核心抽象是统一 Inventory + 可组合过滤器。** toolset、单工具
   allowlist、exclude、read-only、token scope 都在同一库存上生效；HTTP 每个
   请求只实例化该 MCP method 真正需要的库存。服务端静态配置是权限上界，
   请求只能缩小，不能放大。
4. **OAuth/PAT 只解决主体和凭证权限，工具可见性不是最终授权边界。**
   Cloudflare API 和 GitHub API 都会在下游再次执法。GitHub 对无法探测 scope
   的 fine-grained PAT/GitHub App token 仍会展示工具；因此 ThesisTrace 不能把
   `tools/list` 过滤当成对象所有权或租户授权。
5. **GitHub 的高风险控制比 Cloudflare 的通用 Code Mode 更适合 ThesisTrace。**
   严格 read-only、排除列表优先、危险 scope 显式 opt-in，以及删除仓库时把
   已确认目标封入客户端持有的加密 request state；缺少密钥时干脆不暴露删除
   工具。这些模式可直接转化为研究创建、取消、停止和未来删除操作的控制。
6. **ThesisTrace V1 应先做少量领域 typed tools，不应做 Code Mode。** 当前
   Core 的产品资源和动作远少于 2,500 个端点；一个薄 MCP adapter、一个统一
   capability registry、默认只读工具集、写操作显式 opt-in，会更清晰、更容易
   审计，也符合现有 module-first 边界。

## 一、Cloudflare 的当前实现

### 1. 语言、仓库与部署形态

Cloudflare 的通用 API 服务 [`cloudflare/mcp`](https://github.com/cloudflare/mcp)
是 TypeScript Cloudflare Worker。依赖和入口可分别在
[`package.json`](https://github.com/cloudflare/mcp/blob/main/package.json)、
[`src/index.ts`](https://github.com/cloudflare/mcp/blob/main/src/index.ts) 和
[`wrangler.jsonc`](https://github.com/cloudflare/mcp/blob/main/wrangler.jsonc)
中核对：生产入口为 `https://mcp.cloudflare.com/mcp`，使用 Worker Loader、
KV、R2、Analytics Engine 和定时触发器。

它不是通用本地 stdio 产品。开发时通过 Wrangler 在本地启动同一个 HTTP
Worker；对于只支持本地进程 transport 的客户端，Cloudflare 官方指南建议用
`mcp-remote` 做本地代理。Cloudflare 自己的面向用户服务仍是远程 HTTP。
[官方远程 MCP 指南](https://developers.cloudflare.com/agents/model-context-protocol/guides/remote-mcp-server/)

按域拆分的官方服务位于
[`cloudflare/mcp-server-cloudflare`](https://github.com/cloudflare/mcp-server-cloudflare)。
它包含 Documentation、Bindings、Builds、Observability、Browser、Logs、AI
Gateway、AutoRAG、Audit Logs、DNS Analytics、DEX、CASB、Radar 等独立服务。
仓库 README 明确区分：`cloudflare/mcp` 适合广覆盖和代码执行，
`mcp-server-cloudflare` 适合某一产品域内经过策划的 typed tools。

### 2. Transport：新服务无状态，旧会话路径已废弃

Cloudflare 当前官方选择表很明确：

- `createMcpHandler()`：无状态，推荐给新服务；
- `createLegacyMcpHandler()`：仅供旧 `WorkerTransport` 路由临时迁移；
- `McpAgent`：基于 Durable Object/RPC 的旧有状态路径，deprecated。

官方指南甚至提醒现有 quick-deploy template 仍可能使用 deprecated
`McpAgent`，新服务不要照搬。
[Build a Remote MCP server](https://developers.cloudflare.com/agents/model-context-protocol/guides/remote-mcp-server/)、
[Transport](https://developers.cloudflare.com/agents/model-context-protocol/protocol/transport/)、
[Handler API](https://developers.cloudflare.com/agents/model-context-protocol/apis/handler-api/)

生产仓库与文档一致。`cloudflare/mcp` 的
[`src/mcp-handler.ts`](https://github.com/cloudflare/mcp/blob/main/src/mcp-handler.ts)
直接使用 MCP SDK v2 handler factory，每个已认证请求创建一个新的 `McpServer`；
没有 MCP session ID、transport state、replay store、Durable Object 或 async
context bridge，并把 `maxSubscriptions` 设为 0。仓库自己的
[`AGENTS.md` 架构说明](https://github.com/cloudflare/mcp/blob/main/AGENTS.md)
明确记录了这条边界。

产品域服务也已经统一为无状态 Streamable HTTP：`/mcp` 和 `/sse` 都指向同一
SDK v2 handler；`/sse` 只是 URL 兼容别名，不再使用 deprecated HTTP+SSE，
旧式 `GET /sse` 返回 `410 Gone`。
[`mcp-server-cloudflare` README](https://github.com/cloudflare/mcp-server-cloudflare#readme)

### 3. OAuth、API token 与权限边界

Cloudflare 提供独立的
[`@cloudflare/workers-oauth-provider`](https://github.com/cloudflare/workers-oauth-provider)
库，为 Worker HTTP API/MCP 提供 OAuth 2.1 provider 和 protected-resource
能力。它需要 `OAUTH_KV`，支持 PKCE、protected-resource metadata、token
撤销/刷新、scope、Client ID Metadata Documents（CIMD）以及兼容用 DCR。
当前实现文档说明 MCP 2026-07-28 已倾向 CIMD，新实现不应把 DCR 当首选。
核心实现位于
[`src/oauth-provider.ts`](https://github.com/cloudflare/workers-oauth-provider/blob/main/src/oauth-provider.ts)。
Cloudflare 的
[Authorization 文档](https://developers.cloudflare.com/agents/model-context-protocol/protocol/authorization/)
同时明确区分 authentication 与 authorization，并要求把身份/权限 context
用于 handler 内检查或按权限条件注册工具。

`cloudflare/mcp` 支持两条凭证路径：

- 推荐的 Cloudflare OAuth：用户登录并选择权限；OAuth provider 验证它自己
  签发的 MCP access token，再恢复加密的上游 Cloudflare OAuth props；
- 直接 bearer Cloudflare API token：适合 CI/自动化，由
  [`src/auth/api-token-mode.ts`](https://github.com/cloudflare/mcp/blob/main/src/auth/api-token-mode.ts)
  验证并转换成同一份 request-local auth props。

入口在 [`src/index.ts`](https://github.com/cloudflare/mcp/blob/main/src/index.ts)
中启用 `/authorize`、`/token`、`/register`、CIMD、protected-resource metadata，
并设置 access/refresh token 生命周期。MCP handler 只接收经过 Zod 验证的
auth props。

真正的访问上界仍由 Cloudflare OAuth grant/API token permission 和下游
Cloudflare API 执法决定。Code Mode 的 `execute` 是一个可同时承载读写请求的
通用工具；公开实现没有 GitHub 式独立全局 read-only 模式。因此需要只读时，
应签发只读 scope/token，而不能只依赖工具名或模型自律。

### 4. 工具注册与动态发现

#### Code Mode：服务端搜索后执行

[`cloudflare/mcp` README](https://github.com/cloudflare/mcp#tools) 记录了默认仅
暴露三个工具：

| 工具 | 作用 |
| --- | --- |
| `docs` | 搜索 Cloudflare 官方开发文档 |
| `search` | 执行 agent 生成的 JavaScript，在服务端 OpenAPI `spec.paths` 中找端点 |
| `execute` | 执行 agent 生成的 JavaScript，通过 `cloudflare.request()` 调 API |

这把约 2,500 个 API 端点的 schema 从约 244k tokens 压缩到约 1.1k tokens。
这里的“动态发现”不是动态注册几千个 MCP tools，而是把完整 OpenAPI spec 留在
服务端，让 agent 先调用 `search` 找到 method/path/schema，再调用 `execute`。

安全边界也在服务端：`search` 的隔离 Worker 无网络，`execute` 的 outbound
只允许 Cloudflare API；token 通过宿主 props 使用，不进入 agent 生成代码的
隔离环境。实现和限制可在
[`src/tools/search.ts`](https://github.com/cloudflare/mcp/blob/main/src/tools/search.ts)、
[`src/tools/execute.ts`](https://github.com/cloudflare/mcp/blob/main/src/tools/execute.ts)
和 [`AGENTS.md`](https://github.com/cloudflare/mcp/blob/main/AGENTS.md) 中核对。

OpenAPI spec 由 [`src/index.ts`](https://github.com/cloudflare/mcp/blob/main/src/index.ts)
的 daily scheduled handler 拉取、解 `$ref` 后写入 R2，分别保存
`spec.json`、`products.json` 和预计算的 `non-codemode-tools.json`。

#### 非 Code Mode：协议 schema 全量列出，调用时惰性分派

`?codemode=false` 会把每个 API operation 作为独立工具公开，schema 由 OpenAPI
path/query/body 生成，直接调用 API，不执行 agent 代码。由于约 2,500 个工具
会显著扩大上下文，这只是客户端组合 Code Mode 不方便时的备用接口。
[`Disable Code Mode`](https://github.com/cloudflare/mcp#disable-code-mode)

源码没有为每次请求实例化 2,500 个完整 SDK tool handler，而是从 R2 读取已经
预计算的 protocol-ready schema，并在 `tools/call` 时惰性验证和分派。
[`src/tools/non-codemode.ts`](https://github.com/cloudflare/mcp/blob/main/src/tools/non-codemode.ts)、
[`AGENTS.md`](https://github.com/cloudflare/mcp/blob/main/AGENTS.md)

#### 领域服务：策划好的 typed tools

Cloudflare 自己没有把所有问题都交给 Code Mode。面向单一产品域时，官方仍使用
更少、更有语义的 typed tools。这一点对 ThesisTrace 比“2,500 端点压缩”更有
直接参考价值。
[`Which Cloudflare MCP server should you use?`](https://github.com/cloudflare/mcp-server-cloudflare#which-cloudflare-mcp-server-should-you-use)

### 5. 状态、分页/大结果与可观测性

MCP transport 本身无状态，但应用状态仍存在：OAuth grant/token 在 KV，处理后
OpenAPI artifact 在 R2，规范有进程/请求级缓存。按产品拆分的服务在确有业务
需要时也可使用 Durable Objects；这些都是认证、缓存或产品状态，不是 MCP
protocol session。

通用服务为 API `search`、`execute` 以及非 Code Mode 的 API 调用路径提供了
一致的明确硬上限：
[`src/truncate.ts`](https://github.com/cloudflare/mcp/blob/main/src/truncate.ts)
以每 token 约 4 字符估算，`MAX_TOKENS = 6000`、`MAX_CHARS = 24000`；超限时
截断并附上原始估算尺寸和“缩小查询”的提示。这是比“希望模型少取一点”更可靠
的上下文保护。`docs` 使用独立的结构化搜索结果路径，不能把该常量误称为整个
MCP server 每一种响应的 transport 级上限。

[`wrangler.jsonc`](https://github.com/cloudflare/mcp/blob/main/wrangler.jsonc)
启用 Workers logs/traces，并绑定 Analytics Engine。`src/metrics.ts` 记录
`auth_user` 和 `tool_call`（含 user、tool、error），但 binding 缺失时退化成
no-op，写指标失败也不会破坏工具调用。
[`src/metrics.ts`](https://github.com/cloudflare/mcp/blob/main/src/metrics.ts)

这个 best-effort 模式适合指标，不适合作为高风险业务动作唯一的审计凭证。

## 二、GitHub MCP Server 的当前实现

### 1. 语言、仓库与本地/远程形态

[`github/github-mcp-server`](https://github.com/github/github-mcp-server) 是 Go
服务，handler 使用官方 Go MCP SDK
`github.com/modelcontextprotocol/go-sdk/mcp`。官方发布：

- GitHub 托管的远程服务：`https://api.githubcopilot.com/mcp/`；
- `ghcr.io/github/github-mcp-server` 容器；
- 原生二进制；
- 本地 `stdio`；
- 自托管 `github-mcp-server http` Streamable HTTP。

仓库 README 和 GitHub Docs 都推荐能用 hosted remote 时直接连接远程端点；
不支持远程 MCP 的 host 可运行本地版本。
[`README`](https://github.com/github/github-mcp-server#readme)、
[`GitHub Docs`](https://docs.github.com/en/copilot/how-tos/provide-context/use-mcp-in-your-ide/use-the-github-mcp-server)

GitHub Enterprise Server 支持本地服务，但没有 GitHub 托管的 remote；
`ghe.com` 有相应企业远程端点。这说明 local/remote 是产品部署边界，而不是两套
完全相同的发布物。README 还列出 hosted remote 才有的附加 toolsets/tools，
例如 `copilot_spaces` 和 `github_support_docs_search`；因此开源二进制是核心实现
证据，但不能反推 hosted remote 的完整私有部署内容。

### 2. Transport 与请求生命周期

本地进程使用 stdio。自托管和 GitHub hosted remote 使用 Streamable HTTP。
[`docs/streamable-http.md`](https://github.com/github/github-mcp-server/blob/main/docs/streamable-http.md)

[`pkg/http/handler.go`](https://github.com/github/github-mcp-server/blob/main/pkg/http/handler.go)
为请求建立 server，并调用 `mcp.NewStreamableHTTPHandler`，明确配置
`Stateless: true`。它没有依赖一个粘性 MCP session；共享的是 schema cache、
repo-access cache 等应用级只读/短期缓存。

### 3. OAuth、PAT、GitHub App 与权限边界

#### Hosted remote

远程 GitHub MCP 是 OAuth protected resource，不是 authorization server。
客户端必须先从 GitHub OAuth/GitHub App/OAuth App 获得 token，再以 bearer
发送；PAT 也可以直接使用。GitHub 官方集成文档明确说 remote server 自身不
提供 authentication service，且当前不支持 Dynamic Client Registration。
[`docs/host-integration.md`](https://github.com/github/github-mcp-server/blob/main/docs/host-integration.md)

自托管 `http` 命令保持同一角色：它发布 protected-resource metadata，可选择
开启 scope challenge；客户端使用已有 GitHub OAuth credential，或在每个请求的
`Authorization: Bearer ...` 中传 PAT。它不会把 stdio 的本地浏览器登录流程
隐式搬进 HTTP server。
[`docs/streamable-http.md`](https://github.com/github/github-mcp-server/blob/main/docs/streamable-http.md)

#### Local stdio

当前官方二进制/镜像可以在第一次运行时通过浏览器 OAuth 登录：优先使用带
PKCE 的 loopback authorization-code flow，不能回调时使用 device-code flow，
所得 token 只留在内存，不写磁盘。静态 PAT 环境变量优先于 OAuth。
非交互部署可使用 GitHub App installation token；GitHub App 提供更细粒度的
resource permission 和短期 token。
[`docs/oauth-login.md`](https://github.com/github/github-mcp-server/blob/main/docs/oauth-login.md)

#### Scope 与工具可见性

GitHub 对不同 credential 的“工具过滤”能力不相同：

- classic PAT：启动时以 HEAD API 的 `X-OAuth-Scopes` 探测 scope，隐藏明显
  不可用工具；
- remote OAuth：调用需要额外 scope 的工具时返回 scope challenge，让客户端
  重新授权；
- fine-grained PAT、GitHub App installation token、server-to-server token：
  scope 不可按同样方式探测，因此所有工具可能可见，GitHub API 在调用时执法；
- classic PAT 的 scope 探测失败时，当前实现记录 warning 后继续，不过滤工具。

[`docs/scope-filtering.md`](https://github.com/github/github-mcp-server/blob/main/docs/scope-filtering.md)

所以“工具被列出”只表示 server 愿意路由，不表示该主体对目标 repo/object 有
访问权。下游 API 执法才是最后边界。ThesisTrace 应保留这个分层，但对无法
判断主体/workspace 的情况应 fail closed，而不是照搬可用性优先的 fail open。

### 4. Inventory、toolset 与当前的动态发现

GitHub 的 [`pkg/inventory/registry.go`](https://github.com/github/github-mcp-server/blob/main/pkg/inventory/registry.go)
把 tools、resources、prompts、aliases、toolset metadata、read-only 属性和过滤器
放在统一 `Inventory` 中。工具定义由
[`pkg/github/tools.go`](https://github.com/github/github-mcp-server/blob/main/pkg/github/tools.go)
按 toolset 注册，再由
[`pkg/github/server.go`](https://github.com/github/github-mcp-server/blob/main/pkg/github/server.go)
构造实际 MCP server。

公开配置可组合：

- 官方 `server-configuration.md` 仍列出默认 toolsets 为 `context`、`repos`、
  `issues`、`pull_requests`、`users`，但当前
  [`pkg/github/tools.go`](https://github.com/github/github-mcp-server/blob/main/pkg/github/tools.go)
  已同时把 `copilot` 标为 `Default: true`；这说明隐式默认面会随版本变化，生产
  配置应使用显式 allowlist；
- `--toolsets` / `GITHUB_TOOLSETS` 或远程 `X-MCP-Toolsets`、`/x/{toolset}`；
- `--tools` / `GITHUB_TOOLS` 或远程 `X-MCP-Tools`；
- `--exclude-tools` 或远程 `X-MCP-Exclude-Tools`；
- read-only、lockdown、insiders/features。

`exclude` 优先于 allowlist，read-only 再严格过滤写工具。在 HTTP 模式，服务
启动参数是上界：请求 header/path 可以缩小或启用更严格模式，不能越过服务端
上限。
[`docs/server-configuration.md`](https://github.com/github/github-mcp-server/blob/main/docs/server-configuration.md)

HTTP 下还有一层性能优化：`Inventory.ForMCPRequest` 根据 MCP method 生成
request-specific inventory。`tools/list` 才带全部允许工具；`tools/call` 只注册
被调用的那个工具；resources/prompts 也同理；既有 read-only/toolset/scope
过滤仍全部保留。这是“按请求惰性装配”，不是放宽权限。
[`pkg/inventory/registry.go`](https://github.com/github/github-mcp-server/blob/main/pkg/inventory/registry.go)

需要特别澄清：截至 2026-08-26，当前 `main` 的 README 与
[`cmd/github-mcp-server/main.go`](https://github.com/github/github-mcp-server/blob/main/cmd/github-mcp-server/main.go)
均没有 `--dynamic-toolsets` 或 model-callable `enable_toolset`。当前可靠合同是
标准 `tools/list` + operator/client 过滤，以及供人/调试使用的
`github-mcp-server tool-search` CLI；不应依据旧材料推断当前存在动态启用
toolset 的协议。

### 5. 只读、提示注入与高风险动作

GitHub 的 read-only 是服务端严格过滤器：即使某个 toolset 或 `--tools` 显式
请求写工具，也不会把它注册出来。远程可以使用 `X-MCP-Readonly` 或
`/readonly`；本地使用 `--read-only` / `GITHUB_READ_ONLY`。
[`Read-Only Mode`](https://github.com/github/github-mcp-server#read-only-mode)、
[`server-configuration.md`](https://github.com/github/github-mcp-server/blob/main/docs/server-configuration.md)

lockdown 是另一回事：它尽力过滤公共仓库中没有 push 权限的作者内容，以降低
prompt injection 风险，但官方明确说明它不是 authorization boundary，而且
相同 credential 仍可能通过其他工具/API 取得被过滤内容。这个术语边界值得
保留：内容信任过滤不能冒充权限控制。
[`Lockdown Mode`](https://github.com/github/github-mcp-server#lockdown-mode)

删除仓库使用更强的 multi-round-trip elicitation：确认后的精确目标保存在
client-held encrypted request state 中；HTTP 副本共享稳定的 Base64 32-byte
`GITHUB_MCP_SERVER_MRTR_STATE_KEY` 才能验证重试。变量缺失时不暴露
`delete_repository`，格式错误时拒绝启动。高风险 `delete_repo` scope 也需要
显式 opt-in。
[`Repository deletion and request-state encryption`](https://github.com/github/github-mcp-server/blob/main/docs/streamable-http.md#repository-deletion-and-request-state-encryption)、
[`cmd/github-mcp-server/main.go`](https://github.com/github/github-mcp-server/blob/main/cmd/github-mcp-server/main.go)

这里最值得借鉴的是：确认绑定规范化后的精确目标、确认状态防篡改、跨副本可
验证、基础设施不完整时不注册危险工具。

### 6. 分页、大结果与可观测性

GitHub 主要在工具 schema 内控制结果：

- REST 风格 `page`/`perPage`，通常 `perPage <= 100`；
- GraphQL/新 issue 接口使用 `after` cursor；
- `fields` / `field_names` 做 projection，文档明确建议省略 `body`、reaction、
  field values 等大字段；
- Actions/log 工具提供 tail/window 选项；CLI 的 `--content-window-size` 默认
  5000，供相应内容工具使用。

例子可直接在 [`README 的工具 schema`](https://github.com/github/github-mcp-server#tools)
和 [`cmd/github-mcp-server/main.go`](https://github.com/github/github-mcp-server/blob/main/cmd/github-mcp-server/main.go)
核对。当前公开源码没有建立类似 Cloudflare `truncate.ts` 的“所有工具统一约
24 KB”硬上限；GitHub 更依赖每个工具的分页、字段投影和内容窗口。

自托管服务使用 Go `slog`。无日志文件时 INFO 写 stderr；配置 log file 时以
`0600` 创建并启用 DEBUG；`--enable-command-logging` 可记录命令请求/响应，默认
不启用。
[`pkg/http/server.go`](https://github.com/github/github-mcp-server/blob/main/pkg/http/server.go)、
[`cmd/github-mcp-server/main.go`](https://github.com/github/github-mcp-server/blob/main/cmd/github-mcp-server/main.go)

[`pkg/observability/observability.go`](https://github.com/github/github-mcp-server/blob/main/pkg/observability/observability.go)
定义可注入的 logger + metrics 接口，但当前公开 HTTP bootstrap 注入的是
`metrics.NewNoopMetrics()`。因此可以确认公开自托管版本有日志和 metrics seam，
不能从公开源码推断 GitHub hosted remote 的内部遥测实现。

## 三、横向比较

| 维度 | Cloudflare 当前实现 | GitHub 当前实现 |
| --- | --- | --- |
| 主仓库/语言 | `cloudflare/mcp`，TypeScript Worker；另有领域服务 monorepo | `github/github-mcp-server`，Go 二进制/容器 |
| 托管形态 | Cloudflare Workers 远程服务；Wrangler 本地 HTTP 开发 | GitHub hosted remote；本地 stdio；容器/二进制；可自托管 HTTP |
| Transport | 新服务无状态 Streamable HTTP；`McpAgent` 旧路径 deprecated | stdio 或无状态 Streamable HTTP (`Stateless: true`) |
| OAuth 角色 | `workers-oauth-provider` 可同时承载 OAuth provider/protected resource；也接直接 API token | hosted remote 是 resource server，client 自行取 token；PAT 可用；DCR 不支持 |
| 工具规模策略 | 超大面：`docs/search/execute` Code Mode；小域：curated typed tools | 统一 Inventory，按 toolset/tool/read-only/scope 过滤 |
| 动态发现 | agent 在服务端 OpenAPI 上 `search`，再 `execute`；非 Code Mode 惰性 dispatch | 标准 `tools/list` + request-specific inventory；当前 main 无 `dynamic-toolsets` |
| 权限边界 | OAuth/API token scope + Cloudflare API；Code Mode 工具本身不是 read-only 边界 | server filter + token scope visibility + GitHub API 对对象权限执法 |
| 协议状态 | 无 MCP session；KV/R2/cache 是认证和应用状态 | HTTP 无协议 session；schema/cache 是应用状态；stdio 有进程寿命 |
| 大结果 | API 搜索/执行路径统一约 6k token/24 KB 截断 + 服务端搜索 | 按工具分页、cursor、projection、content window；未见统一全局 cap |
| 只读/危险操作 | 通用服务依靠只读 token/scope；生成代码隔离、受限 outbound、token 不进 isolate | 严格 read-only、exclude、危险 scope opt-in、删除 multi-round confirmation |
| 可观测性 | Workers logs/traces + Analytics Engine auth/tool metrics；metrics best effort | `slog` + 可选 command log；metrics seam，公开 HTTP 默认 no-op |

## 四、对 ThesisTrace 的建议

### 1. 推荐的边界

当前 [`ThesisTrace Core Architecture`](../architecture/core.md) 明确：产品是
module-first 的本地单操作者闭环；HTTP/Worker 只是 adapter；业务生命周期状态
在 PostgreSQL，immutable Result/Checkpoint bytes 在 RustFS；当前没有 login、
tenancy、collaboration 或 hosted product mode。

因此第一版 MCP 应是 Core 外层的薄 adapter，而不是新的业务执行引擎：

```text
Agent
  ├─ local stdio adapter（开发/单操作者）
  └─ stateless Streamable HTTP adapter（需要远程时）
             │
             ▼
     one Capability Registry
             │
             ▼
     ThesisTrace application/module interfaces
             │
             ├─ PostgreSQL product state
             ├─ RustFS immutable artifacts
             └─ existing Research/Batch/Tracking workers
```

不要让 MCP handler 直接查询业务表、读取 RustFS object key 或执行研究内核；它应
调用与现有 HTTP adapter 同级的 application/module interface。长任务立即返回
durable resource ID，agent 再轮询 status/result summary。

若未来需要公网 hosted MCP，可在前面增加 Cloudflare Worker 做 OAuth resource
gateway、rate limit、固定 Host/Origin、edge audit 和私网转发，但它不能替代
Core 的 workspace/owner authorization。当前 Core 没有 tenancy；在建立该边界
前，远程部署只能是一套实例对应一个受控 operator/workspace，不能声称支持
多租户。

### 2. 建议建立一个统一 Capability Registry

借鉴 GitHub Inventory，stdio 和 HTTP 必须从同一 registry 注册，不应复制两套
tool definitions。每项至少包含：

```text
name
description
input_schema / output_schema
toolset
required_scope
read_only
destructive
costly_or_long_running
idempotent / request_id_required
handler
```

过滤顺序建议固定为：

```text
deployment allowlist（绝对上界）
  -> subject/workspace scope
  -> requested toolsets/tools（只可缩小）
  -> explicit excludes
  -> read-only filter
  -> named tool lazy dispatch
```

即使工具未因 scope 被隐藏，handler 仍必须校验主体、workspace 和具体
ResearchRun/DailyTrack 所有权；`tools/list` 不是授权凭证。

### 3. 第一版工具集建议

默认只开启少量 read-only typed tools：

- `context`：产品能力、当前数据覆盖、alpha catalog、formula diagnostics；
- `research_read`：列出/读取 Research Folder、ResearchRun、Result summary；
- `batch_read`：Batch 状态、child run summary；
- `tracking_read`：DailyTrack 状态和最新 checkpoint summary。

写工具显式 opt-in：

- `research_write`：创建 ResearchRun、请求取消；
- `batch_write`：创建 Research Batch、请求取消；
- `tracking_write`：从成功 Strategy Result 创建 DailyTrack、retry、stop，以及对
  已 stopped Track 的显式删除；
- `folder_write`：创建/重命名/移动研究组织资源（若当前 Core 能力允许）。

Data Operator、schema initialization、GC、private checkpoint、attempt lease、直接
publication object 操作不应进入 agent-facing MCP。它们是部署私有/operator
能力，不是普通产品工具。

### 4. 长任务、幂等与高风险控制

- 创建/取消/停止等动作保留 Core 已有的 `request_id`/action receipt 语义；MCP
  重试不得生成重复 ResearchRun 或重复动作。
- 创建研究只返回 `run_id`、admission outcome、状态和紧凑 diagnostics；不要在
  一个调用里等待完整研究。
- 对取消、停止、未来删除等动作，借鉴 GitHub：先返回结构化影响范围并 elicitation
  确认；确认绑定规范化的 resource ID、当前 version/state 和动作；使用防篡改且
  短时有效的 request state；无法验证时不暴露危险工具。
- “高算力/长时运行”虽未必 destructive，也应标记为 costly，要求 agent 明示
  period、universe、research kind 等实际成本驱动参数。scope 与用户确认是两层
  独立控制。
- 保留一键全局 read-only server mode；deployment read-only 是绝对上界，任何
  client header/config 均不可打开写权限。

### 5. 上下文和大结果

ThesisTrace 当前工具数量有限，应采用 Cloudflare 领域服务/GitHub 的 typed tool
模式，不采用通用 `search + execute arbitrary code`。只有未来能力增长到数百或
数千且 schema 明显挤占上下文时，才评估服务器端 capability search；即使如此，
也不应把读写混进一个无差别的通用 `execute`。

所有列表采用稳定 cursor 和有限 page size，并提供 fields/projection。大型 Result
不内联完整 JSON/Parquet/报告：

- MCP tool 返回 summary、resource ID、schema、coverage、row count、hash；
- MCP resource 或短时授权 artifact URL 承载可按需读取的报告；
- 全局保留一个确定性的 byte/token cap，并返回 `truncated`、原始估算大小、
  `next_cursor` 或“改用 artifact/resource”的机器可读提示。

建议同时采用 GitHub 的分页/projection 和 Cloudflare 的全局硬 cap；两者解决的
不是同一个问题。

### 6. 可观测性与审计

复用 Core 当前结构化 operational event 边界，不记录 formula、hypothesis、
headers、credentials、完整 arguments 或 result body。MCP adapter 应增加稳定的
工具调用 envelope：

```text
event=mcp_tool_call
subject_id / workspace_id（有 hosted auth 后）
tool_name
resource_id
request_id
outcome / error_code
latency_ms
response_bytes
http_request_id
```

普通 metrics/traces 可像 Cloudflare 一样 best effort；但 destructive/costly
动作需要的授权、确认和 action receipt 必须进入 Core 权威 product state，不能
只依赖会丢失的日志或 Analytics Engine datapoint。

## 五、应借鉴与不应照搬

### 应借鉴

- 无状态 Streamable HTTP；业务状态留在 Core durable resources；
- GitHub 式统一 capability inventory 和 toolset/read-only/exclude 过滤；
- deployment 配置作为权限上界，请求只能缩小；
- 少量领域 typed tools，列表使用 cursor + fields projection；
- Cloudflare 式全局响应硬上限和明确 truncation metadata；
- OAuth subject 到 workspace/scope 的映射，以及 handler 内对象级再次授权；
- GitHub 高风险动作的精确目标确认、防篡改 request state、缺配置即不暴露；
- Cloudflare 隔离执行环境、固定 Host/Origin、credential 不进入不可信代码；
- 日志、指标与 durable action receipt 分层。

### 不应照搬

- **不照搬 Cloudflare Code Mode。** ThesisTrace 不是 2,500 端点的通用云 API，
  任意代码执行会增加权限解释、确认、测试和审计复杂度。
- **不把 Cloudflare Worker 当研究执行器。** 研究、Batch 和 Tracking 继续由现有
  Core workers 管理；边缘 Worker 至多是远程认证/网关。
- **不把 Durable Object/MCP session 当业务状态。** 当前官方路径已经无状态，
  ResearchRun/Batch/DailyTrack 才是恢复和轮询依据。
- **不照搬 GitHub scope 探测失败后的 fail open。** ThesisTrace 无法确认主体、
  workspace 或对象权限时应拒绝，不应只显示工具后期待下游报错。
- **不照搬 GitHub 的兼容 alias/旧名保留。** 本仓库明确不做兼容、fallback 和
  migration；MCP contract 变更应 hard cut 并同步更新测试/文档。
- **不把 read-only hint 当安全边界。** annotation 方便 agent 规划；真正边界是
  服务端过滤、scope、对象授权、幂等 receipt 和确认状态。
- **不对 agent 暴露 Data Operator/内部执行资源。** private operator、attempt、
  checkpoint、GC 和物理 artifact key 都不属于产品 MCP surface。

## 已核验的一手来源

### Cloudflare 官方文档

- [Build a Remote MCP server](https://developers.cloudflare.com/agents/model-context-protocol/guides/remote-mcp-server/)
- [MCP transport](https://developers.cloudflare.com/agents/model-context-protocol/protocol/transport/)
- [MCP handler APIs](https://developers.cloudflare.com/agents/model-context-protocol/apis/handler-api/)
- [MCP authorization](https://developers.cloudflare.com/agents/model-context-protocol/protocol/authorization/)

### Cloudflare 官方仓库

- [`cloudflare/mcp` README](https://github.com/cloudflare/mcp#readme)
- [`cloudflare/mcp` architecture notes](https://github.com/cloudflare/mcp/blob/main/AGENTS.md)
- [`cloudflare/mcp` package](https://github.com/cloudflare/mcp/blob/main/package.json)
- [`src/index.ts`](https://github.com/cloudflare/mcp/blob/main/src/index.ts)
- [`src/mcp-handler.ts`](https://github.com/cloudflare/mcp/blob/main/src/mcp-handler.ts)
- [`src/server.ts`](https://github.com/cloudflare/mcp/blob/main/src/server.ts)
- [`src/truncate.ts`](https://github.com/cloudflare/mcp/blob/main/src/truncate.ts)
- [`src/metrics.ts`](https://github.com/cloudflare/mcp/blob/main/src/metrics.ts)
- [`wrangler.jsonc`](https://github.com/cloudflare/mcp/blob/main/wrangler.jsonc)
- [`cloudflare/mcp-server-cloudflare` README](https://github.com/cloudflare/mcp-server-cloudflare#readme)
- [`cloudflare/workers-oauth-provider` README](https://github.com/cloudflare/workers-oauth-provider#readme)
- [`workers-oauth-provider/src/oauth-provider.ts`](https://github.com/cloudflare/workers-oauth-provider/blob/main/src/oauth-provider.ts)

### GitHub 官方文档与仓库

- [Using the GitHub MCP Server in your IDE](https://docs.github.com/en/copilot/how-tos/provide-context/use-mcp-in-your-ide/use-the-github-mcp-server)
- [`github/github-mcp-server` README](https://github.com/github/github-mcp-server#readme)
- [`docs/host-integration.md`](https://github.com/github/github-mcp-server/blob/main/docs/host-integration.md)
- [`docs/oauth-login.md`](https://github.com/github/github-mcp-server/blob/main/docs/oauth-login.md)
- [`docs/scope-filtering.md`](https://github.com/github/github-mcp-server/blob/main/docs/scope-filtering.md)
- [`docs/server-configuration.md`](https://github.com/github/github-mcp-server/blob/main/docs/server-configuration.md)
- [`docs/streamable-http.md`](https://github.com/github/github-mcp-server/blob/main/docs/streamable-http.md)
- [`cmd/github-mcp-server/main.go`](https://github.com/github/github-mcp-server/blob/main/cmd/github-mcp-server/main.go)
- [`pkg/http/handler.go`](https://github.com/github/github-mcp-server/blob/main/pkg/http/handler.go)
- [`pkg/http/server.go`](https://github.com/github/github-mcp-server/blob/main/pkg/http/server.go)
- [`pkg/inventory/registry.go`](https://github.com/github/github-mcp-server/blob/main/pkg/inventory/registry.go)
- [`pkg/github/server.go`](https://github.com/github/github-mcp-server/blob/main/pkg/github/server.go)
- [`pkg/github/tools.go`](https://github.com/github/github-mcp-server/blob/main/pkg/github/tools.go)
- [`pkg/observability/observability.go`](https://github.com/github/github-mcp-server/blob/main/pkg/observability/observability.go)
