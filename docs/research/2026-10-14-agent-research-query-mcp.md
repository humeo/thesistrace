# 面向 Agent 的研究记录查询 MCP 调研

Date: 2026-10-14

建议扩展现有 `list_research_runs`，统一承担研究记录查找、结构化过滤和全局指标排序；保留按 ID 的详情工具。复用 Core 查询规则，分别保留 Web 页码和 MCP 游标。下面保留设计阶段的外部证据与本地核对；后续实现及实测结果见[实施验收](2026-10-14-agent-research-query-validation.md)。

## 外部一手来源调研

本节研究查找、指标过滤、排名和详情读取的工具契约，不代表功能已经实现或通过真实 Agent 验收。
来源限于 MCP 规范、模型厂商官方工程文档、GitHub 官方 MCP 源码和 PostgreSQL 官方文档。
GitHub 源码以调研日读取的 `main` 为准；链接随上游更新，本节不推断其托管服务已部署同一版本。

### 1. 先区分协议、经验建议和产品取舍

截至调研日，MCP 的 `latest` 页面指向 **2026-07-28**。
协议规定工具如何声明和调用；它没有规定业务发现工具必须叫 `search`，也没有要求所有查询都接受自然语言。
工具拥有名称、描述、输入 JSON Schema；输出 schema 是可选的，声明后结构化结果必须符合该 schema。
参数约束和业务错误应返回 Agent 可以据此修正的工具错误；未知工具、请求信封不合法等属于协议错误。
这些属于当前规范的要求，不意味着本次功能需要顺带升级仓库 MCP SDK 或传输版本。[MCP Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)

MCP Pagination 规范明确列出的操作是 `resources/list`、`resources/templates/list`、`prompts/list`、`tools/list`。
其中的不透明 cursor、`nextCursor`、服务端决定页大小等约定适用于这些协议目录操作。
**`tools/list` 是列出工具定义，不是调用 `list_research_runs` 列出研究记录。**
业务查询 tool 可以自行定义 `limit`、页码或游标；不能把目录分页规则当成它的强制协议。[MCP Pagination](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/pagination)

下文中“官方经验”表示作者的工程建议或其产品实践；“本项目建议”是结合当前需求做出的推论。
工具数量、是否更名、默认数量、排序口径和游标一致性都需要由产品契约明确，协议不会代为决定。

### 2. 官方对 Agent 工具的经验

Anthropic 的相关建议集中在减少 Agent 为完成任务所需处理的信息：

- 提供能直接完成高价值工作流的工具，避免让模型读取全部联系人再自行寻找目标。
- 工具职责应清楚，重叠工具会增加选择困难；内部可合并经常连续执行的操作。
- 返回有用上下文，限制结果量；分页、过滤和摘要都是可用手段。
- 描述要补足新人不知道的领域语义，错误要给可执行的修正指引。
- 用真实任务评估正确率、工具次数、token、错误和时延，并阅读调用记录。

这里的 `search_contacts` 优于 `list_contacts` 示例针对的是全量遍历，不是对 `list` 这个名称的禁令。[Anthropic: Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)

OpenAI 的函数调用建议强调清楚的字段说明、枚举和对象结构，让模型少猜测、少计算已知信息。
它建议合并总是连续调用的函数，并通过评估确定工具面；“少于 20 个初始函数”只是软建议。
OpenAI strict mode 的 schema 限制属于该 API，不是通用 MCP 规范；不能直接反推所有 MCP 参数必须必填。[OpenAI: Function calling](https://developers.openai.com/api/docs/guides/function-calling#best-practices-for-defining-functions)

OpenAI 当前工具规划文档直接以 `list_projects` 发现项目、`get_project` 查看详情为例。
它要求围绕用户目标设计工具，明确输入、输出、授权和失败行为，并说明与相似工具的边界。
因此，“有边界的集合查询 + 按 ID 的详情读取”有直接官方先例，不必增加同义搜索工具。[OpenAI: Define tools](https://developers.openai.com/plugins/plan/tools)

另一个容易混淆的边界是 ChatGPT deep research/company knowledge 的兼容接口。
OpenAI 为该产品集成定义 `search(query)` 和 `fetch(id)`，搜索结果使用可引用的文档 ID、标题和 URL。
这不能推广成所有业务 MCP 必须只有 `search`/`fetch`，也不能迫使精确指标过滤塞进字符串。[OpenAI: Building MCP servers](https://developers.openai.com/api/docs/mcp#create-an-mcp-server)

### 3. 成熟实现：GitHub 官方 MCP

`search_repositories` 并非把全部仓库返回给模型：它接收查询、`sort`、`order` 和分页参数，交给 GitHub Search API。
`query` 复用 GitHub 已有高级查询语法，排序字段和方向仍是枚举；`minimal_output` 默认 `true`。
结果保留 `total_count`、`incomplete_results` 和精简对象，允许调用者区分总匹配量与实际返回量。
这里值得复用的是复用成熟查询能力、显式排序与有界输出，不是其兼容分支。[GitHub: SearchRepositories](https://github.com/github/github-mcp-server/blob/main/pkg/github/search.go)

`search_issues` 的当前源码更能说明“query 的语义必须精确”：
它为语义搜索和 GHES 的词法搜索生成不同描述；前者引导自然语言，后者明确使用 GitHub 搜索语法。
同时保留 `sort`、`order`、可选 owner/repo 和 `fields` 投影，避免所有控制混成一个字符串。
不能因为工具名包含 search，就对一个子串匹配实现宣称支持语义理解。[GitHub: SearchIssues](https://github.com/github/github-mcp-server/blob/main/pkg/github/issues.go#L1803)

GitHub 同时有 `list_issues`、`search_issues`、`issue_read`，但其上下文、查询能力和读取深度不同。
这说明可在需求边界不同的时候拆分；不能据此给同一组本地筛选条件再建两个入口。[GitHub 官方工具目录](https://github.com/github/github-mcp-server#issues)

`WithPagination` 给业务搜索加入 `page` 和 `perPage`，范围为每页 1–100；同仓库另有仅游标的 helper。
这也是业务 tool 的分页参数由业务 API 选择，而非受 `tools/list` 页大小规则约束的直接实例。[GitHub: pagination helpers](https://github.com/github/github-mcp-server/blob/main/pkg/github/params.go#L320)

### 4. 本项目建议：一个发现入口，保留详情入口

以下为产品取舍，不是 MCP 强制规则。

| 方案 | 适用情形 | 对当前需求的判断 |
| --- | --- | --- |
| 扩展 `list_research_runs` | 同一研究集合增加搜索、过滤和排序 | 优先；保留唯一发现入口，描述明确其查找能力 |
| 改为 `search_research_runs` | 现有工具名在真实评估中持续导致误用 | 需要评估证据；如果改名应统一替换，不长期双轨 |
| 同时保留 list 和 search | 范围、索引、结果语义或用途明显不同 | 暂无充分理由；不能只因一个有 keyword、一个没有就拆分 |
| 增加 `get_best_strategies` | 产品已经定义固定、可解释的综合评分 | 当前“最好”没有唯一含义，不宜藏入工具名 |

搜索、过滤、排序都在回答“哪些现有研究记录符合条件”，可以属于同一个读取动作。
排名后的候选列表应已经足够回答简单比较；只在需要解释策略内容或检查完整设定时读取详情。
不要让 Agent 必须先列出所有 ID，再对每条详情发请求，才能获得列表本来就知道的指标。
这个选择符合前述避免职责重叠和减少无效上下文的经验，但它是否改善 Agent 表现仍需评估。

### 5. 本项目建议：明确 JSON 参数，文本查询只承诺已实现的能力

有限指标、固定比较符、固定排序字段适合显式结构化参数。
GitHub 使用 DSL 的前提是已有成熟、公开、完整的 GitHub 搜索语法；本项目不应为几个数字条件新造一套语言。
若未来确有复杂布尔组合和大量字段需求，再依据真实任务重新评估，不能提前抽象成通用查询 AST。

| 参数语义 | 对 Agent 必须说明的内容 |
| --- | --- |
| 文本搜索 | 匹配哪些字段、子串还是分词、是否区分大小写、多词如何组合 |
| 指标名 | 有限枚举、中文概念对应关系、适用研究类型 |
| 比较符 | `gt/gte/lt/lte` 的严格或包含边界语义 |
| 阈值 | 数值单位、百分比表示方法、最大回撤正负号 |
| 多个条件 | 同时成立还是任选一个成立；是否允许同一指标上下界 |
| 排序 | 字段、方向、缺失指标位置、同分顺序、默认顺序 |
| folder/kind | 省略代表整个账户还是当前文件夹，类型之间能否混排 |
| limit/cursor | 页大小上限、续页方式、修改条件时如何重新查询 |

结构示意只表达形状，实际指标枚举、单位和默认值必须由仓库领域契约确认：

```json
{
  "research_kind": "strategy_backtest",
  "status": "succeeded",
  "search": "动量",
  "metric_filters": [
    { "metric": "sharpe", "operator": "gte", "value": 1.0 }
  ],
  "sort_by": "sharpe",
  "sort_direction": "descending",
  "limit": 5
}
```

不能把“回撤低于 20%”的自然语言原文交给服务端临时解释；Agent 应按字段说明生成明确数字。
也不能默认“高收益”等于“高年化超额收益”；工具描述必须说明指标相对于什么基准。
未知字段、未知指标和非法输入应明确拒绝，不能静默忽略后返回看似成功的列表。
语法合法但互相矛盾的数值条件可确定地返回空集合；本项目建议采用这一语义，且不自动放宽条件。单位由 schema 清楚说明，不在运行时猜测并转换用户数值。

### 6. 排名正确性：先确定集合，再排序，再截取

PostgreSQL `SELECT` 的逻辑语义是先 `WHERE` 消除不匹配行，再 `ORDER BY` 排序，最后 `LIMIT/OFFSET` 取子集。
稳定分页还需要唯一排序；相同排序值没有唯一 tie-breaker 时，返回顺序并无保证。
PostgreSQL 默认降序会把 NULL 放在前面，因此“最佳指标优先”不能依赖默认空值行为。[PostgreSQL SELECT](https://www.postgresql.org/docs/18/sql-select.html#SQL-SELECT-DESCRIPTION)、[LIMIT/OFFSET](https://www.postgresql.org/docs/18/queries-limit.html)

对本需求，正确的业务含义应为：当前授权范围 → 所有过滤 → 指标排序与固定同分规则 → 页大小限制。
“最新 50 条里挑出夏普最高的 5 条”和“所有匹配记录里夏普最高的 5 条”是不同结果。
权限范围也必须在查询端收窄，不能先取跨用户结果再交给 Agent 判断。
缺失或未完成记录不能被当作指标 0；是否参与默认列表、过滤和指标排名需要分别明确。

游标产品契约建议：

- Agent 原样回传，不解析、不拼接；服务端验证，而非仅在描述里请求遵守。
- 游标绑定当前用户、规范化筛选条件和排序；改变条件时重新从第一页开始。
- 各页都重新鉴权；游标只是定位信息，不能代替访问权限。
- 明确结束信号；坏游标或条件不匹配应报可修正错误，不自动回到第一页。
- 唯一排序不等于跨请求快照；并发新增、删除或指标更新时的一致性承诺必须诚实。
- 不为这个只读查询引入隐式会话、“当前搜索”状态或服务端长期保存整份结果集，除非另有已确认需求。

这些是业务 API 建议；MCP 目录分页页没有为研究记录提供快照、一致性或查询绑定保证。

### 7. 输出边界和失败语义

建议固定 summary，而非开放任意字段选择或第一版就加入多个 verbosity 模式。
summary 优先包含稳定 ID、可识别名称、研究类型、状态、核心指标，以及判断结果可比性所需的最少信息。
全量代码、长备注、净值序列和完整配置留给现有详情或 artifact 读取入口。
必须保留后续调用所需的 ID；只返回漂亮名称会让重名记录无法可靠寻址。

如果存在字节预算，截断应发生在完整记录边界并产生正确下一页定位；不能切断 JSON 或静默丢弃候选。
返回可用的下一页信号，并区分“总匹配量”“本页条数”和“搜索本身不完整”；没有精确计数就不要假称总数。
是否增加 `applied_query` 或说明字段，应先检查当前返回契约和模型 trace，避免重复回显大量输入。

| 情况 | 应有可观察行为 |
| --- | --- |
| 没有匹配 | 成功返回空集合，说明不存在符合当前条件的结果 |
| 无权限或目标不可见 | 使用当前统一权限契约，不泄露他人研究存在性 |
| 参数不合法 | 工具错误指出字段、允许值或正确单位，允许 Agent 修正 |
| 游标不合法或条件改变 | 明确要求移除 cursor 或恢复原查询，不能降级成无筛选查询 |
| 后端查询失败 | 返回失败；不能把失败包装成空集合 |

### 8. 名称和描述也属于被验收的产品契约

工具描述应让只见到 schema 的 Agent 知道：何时调用、搜索什么、排序范围多大、下一步用什么入口。
下面是本项目描述草案的语义，不应在未核对字段和行为前直接复制进代码：

> 查找当前研究者已有的研究记录；可按文件夹、研究类型、文本和指标条件筛选，按一个支持的指标排序并取前 N 条。筛选和排序作用于整个匹配集合。文本查询使用已定义的字面匹配规则。返回摘要；需要完整设定和结果时，使用记录 ID 调用详情工具。

“最好”需要被映射成明确目标：夏普最高、超额收益最高、回撤最小，或者用户定义的限制条件。
工具不应悄悄生成综合评分；Agent 的回答需说清实际采用的排序口径和比较范围。
不同回测时间、数据版本或基准的记录可以被检索，但不因此自动成为同口径的优劣比较。
这些是研究产品的语义要求，不能靠工具名称或 `readOnlyHint` 自动实现。

### 9. 如何证明真实 Agent 会用

Anthropic 的评估文档区分任务、重复 trial、调用记录和最终 outcome；建议尽量检查实际结果，避免固定唯一工具调用路径。
对于非确定性模型，一次成功不足以说明稳定；失败 trace 可区分模型误用与测试环境、评分器问题。[Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

本项目应使用固定、独立且可核算的研究样本，把以下自然语言任务纳入少量代表性评估：

| 用户任务 | 应验证的结果 |
| --- | --- |
| “我所有策略里夏普最高的 5 个” | 第一页之外的优胜记录也能进入正确 top 5 |
| “夏普大于 1，回撤不超过 20%” | AND 条件、单位、正负号和边界正确 |
| “找备注里提到动量的研究” | 按实际文本匹配契约检索，不虚构语义搜索 |
| “再看下一页” | 原样续页，无重复、漏页或条件丢失 |
| “把条件改成夏普大于 2” | 新查询不复用旧游标 |
| “看看最好的是哪些” | 明示评判口径或获得必要澄清，不宣称默认最新就是最佳 |
| “为什么这条排第一，打开看具体设定” | 用准确 ID 获取详情，保留可比性限制 |
| 无结果、缺失指标、重名记录 | 不捏造结果、不把 NULL 当零、不凭名称猜 ID |

确定性工具/数据库验证与真实模型效果评估应分开：前者证明排序、权限、分页和输出契约，后者证明 Agent 理解并使用它们。
效果记录至少包含：正确结果比例、错误参数比例、工具调用数、输出 token、耗时，以及是否把局部结果误称全局排名。
评分重点是结果和业务不变量；允许正确的不同调用顺序，不绑定模型解释原文。
具体测试入口继续以 [AGENTS.md](../../AGENTS.md#testing) 为准，本调研不新增另一套测试运行说明。

本节尚未运行真实模型评估，也未证明改动后的连接端已经重新发现工具 schema。
落地验收仍需检查实际 `tools/list`、真实调用结果，以及内置 Agent 使用同一工具契约的行为。

## 通用查询实践的补充对照

Google AIP-132 将过滤、排序视为集合 List 的合理能力；AIP-158 给出不透明页令牌、查询条件保持一致、令牌不代替鉴权等设计指导。可以借鉴这些性质，但它们是 Google 的 API 设计准则，不是本项目必须照搬的分页字段、默认大小或错误规范。[AIP-132](https://google.aip.dev/132)、[AIP-158](https://google.aip.dev/158)

AIP-160 反而建议可扩展的字符串过滤语言。这是一个值得保留的反例：当产品已有丰富字段与成熟语法时，DSL 有价值。ThesisTrace 目前只需要有限指标、AND 阈值及字面关键词，已有结构化 Filter 和 SQL 白名单，因此选择显式 JSON；这一取舍来自当前需求和已有实现，不宣称“Agent 永远不适合 DSL”。[AIP-160](https://google.aip.dev/160)

## 本地核对与接入结论

代码核对基线：本地 `main@e9957086`。以下是源代码事实；它不证明任一部署环境已经更新。

| 已有事实 | 证据 |
| --- | --- |
| MCP 必须复用 Core Module、返回有界产品语义结果；不直接镜像 HTTP | [ADR-0220](../adr/0220-expose-research-agent-access-through-a-native-core-mcp-adapter.md) |
| MCP Transport Session 不拥有执行或恢复真相，接受明确分页 | [ADR-0222](../adr/0222-keep-research-agent-execution-stateless-and-resource-addressed.md) |
| 当前 MCP list 只有 folder、kind、cursor、limit，默认 20、上限 50 | [输入模型](../../apps/core/src/thesistrace/research_agent/models.py)、[Registry](../../apps/core/src/thesistrace/research_agent/registry.py) |
| HTTP 已暴露 search、metric_filters、sort_by、sort_direction，并调用 list_page | [HTTP Adapter](../../apps/core/src/thesistrace/entrypoints/http.py) |
| list_page 先过滤与数值排序，再分页；含同分顺序、NULLS LAST 和精确总数 | [ResearchRun Module](../../apps/core/src/thesistrace/research_run/service.py) |
| 当前 MCP list 按 created_at DESC、id 排序，Fernet cursor 绑定 Researcher/folder/kind | [ResearchRun Module](../../apps/core/src/thesistrace/research_run/service.py) |
| 列表已有三项策略指标或三项 Rank IC，来自持久化 key_metrics；不用逐条加载 Result | [领域模型](../../apps/core/src/thesistrace/research_run/models.py)、[摘要与指标投影](../../apps/core/src/thesistrace/research_run/service.py) |
| 文本查找是名称/备注/Formula 子串；已有生成搜索列及 pg_trgm 索引，不包含 Python 源码 | [schema](../../apps/core/src/thesistrace/research_run/schema.sql)、[显式搜索迁移](../../apps/core/src/thesistrace/migrations/research_search_0010.py) |
| 完整记录按 32 KiB 业务页预算裁剪，cursor 要基于实际保留前缀 | [fit_page](../../apps/core/src/thesistrace/_paging.py) |
| 内置 Agent 动态发现 MCP 工具，加入自身 ask_user 和业务呈现工具 | [MCP discovery](../../apps/agent/src/mcp-run.ts)、[Agent runtime](../../apps/agent/src/research-runtime.ts) |

### 推荐契约

1. 扩展唯一 `list_research_runs`：复用已有搜索、指标枚举、比较符和单字段排序；增加明确 status、精确 Research Period 和 Universe 条件，以支持成功记录和同区间比较。后三项是本次新增能力，不是当前 HTTP 已实现的筛选。
2. `metric_filters` 使用原生 JSON 数组；六项指标在 JSON Schema 中说明 Kind、单位和方向。所有条件 AND。缺失值不满足阈值，两个排序方向都放在末尾，不把缺失值计作有效 Top N。MCP 要求指标查询显式 Kind；这项模型引导规则不改变 Web 现有的可省略 Kind 契约。
3. 在 ResearchRun Module 内统一规范化查询、WHERE、ORDER 与摘要投影。Web 保留页码；MCP 实现绑定完整查询及排序元组的 keyset cursor。不能只在 Registry 调用 list_page 再包装一个不透明 OFFSET。
4. 摘要补充 Universe；返回精确匹配数量和有界的规范化查询说明，使 Agent 能说明范围。数量与本页来自同一 SQL 语句；字节预算让一页不足 N 时，只补取获得 N 个有效条目所需的页面。多次请求仍是实时视图，不能声称跨页冻结快照。
5. 默认浏览仍按最新。用户说“最好”时，Agent 明示初筛口径，再由服务端排序；不增加隐藏复合评分，不把回测记录当成独立且已去重的 Strategy 实体。
6. 继续按 ID/Result section 获取候选的冻结条件与证据。不同日期、Universe、费用和 Data Generation 的条目可被查到，但不能自动宣称同口径优劣。

### 为什么不是只加几个 MCP 参数

现有指标 SQL 和索引可复用，但还需处理全条件游标绑定、指标排序的数值/NULL/同分续页、字节裁剪后的继续位置、状态/比较条件与总数，以及可被模型理解的 schema/描述。这些行为应集中在现有 ResearchRun Module，MCP Adapter 保持轻薄。

当前数据已包含所需字段，不需要为了接口接入重算 Result 或建立另一套研究真相；是否增加索引应由受影响查询的实际计划与延迟决定。索引变更如有必要仍须走显式数据库迁移。

### 验证证据的当前边界

已检查现有[指标排序与 Ownership 集成测试](../../apps/core/tests/integration/test_research_run_ownership.py)、[MCP 分页验收](../../apps/core/tests/acceptance/test_core_research_agent_mcp_runs.py)和[Agent eval 定义](../../apps/agent/src/research-eval.ts)。这些证明有可复用的测试入口与 Fixtures；本次没有重新运行它们，也不能把它们当成新查询契约已通过的证据。

现有 Agent eval outcome 主要覆盖创建、纠错、轮询、追踪和解释结果，尚无研究集合查询/排名场景。实施时需要固定包含旧记录高分、NULL、重名、跨 Researcher、不同区间和多页的已知样本，核对真实结果与口径，再独立测模型任务成功率、成本和时延。
