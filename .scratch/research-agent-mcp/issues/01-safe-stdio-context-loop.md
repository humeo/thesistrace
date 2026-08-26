# 01 — 建立安全的 stdio Research Agent 上下文闭环

**What to build:** 让本地 Codex 类 Host 可以通过正式打包的 stdio MCP 进程发现并调用三个安全的研究上下文 Tool，从当前 Core 获得可用于编写 Formula 和提交研究的结构化信息，而不经过产品 HTTP 路由、不获得 Data Operator 权限，也不产生协议会话拥有的业务状态。

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] 使用官方 Python MCP SDK 的当前稳定主版本并锁定有界依赖；stdio 进程可正常初始化、列出 Tool、调用 Tool 和优雅退出，且标准输出不混入非协议内容。
- [ ] 建立一个请求级 Research Agent Capability Registry，统一 Tool 元数据、输入输出 Schema、scope 检查、结构化结果和向 Core module interface 的委托；它不调用现有 HTTP 路由，也不直接访问数据库或对象存储。
- [ ] 本地 stdio 固定绑定 `local_operator`，默认授予 `research:read`、`research:execute`、`tracking:read`、`tracking:execute`，默认不授予 `research:cancel` 或 `tracking:stop`，且 principal 不保存在全局可变状态中。
- [ ] `get_research_context` 返回当前 Data Overview、只读 Research Folders 和现行 authoring constraints，包括 research kinds、universes、neutralization、Strategy 与 Batch 边界；不返回 Data Generation 枚举/选择器或 Folder 修改能力。
- [ ] `get_alpha_catalog` 返回确定性排序的 authorable fields 与 builtins，并支持有界 identifier 过滤；未知 identifier 被显式报告，不被静默忽略。
- [ ] `diagnose_alpha_formula` 返回明确的 valid/invalid 结构、稳定 diagnostic code 和正确 source range，不创建 ResearchRun，也不把可修正错误转换为协议异常。
- [ ] 三个 Tool 都有显式输入/输出 Schema，并标记为 read-only、idempotent、closed-world；当前未实现的 Tool 以及 Prompts、Resources、Sampling、Elicitation、Subscriptions 均不出现在 discovery 中。
- [ ] Capability Registry 契约测试和真实 stdio 协议测试覆盖成功、非法输入、缺失 Core 上下文、确定性排序、进程退出与日志隔离；测试不依赖公网或真实模型。
- [ ] 相关 Python 检查、确定性测试和现有受影响门禁通过，失败时保留退出码、trace ID 和经净化的协议诊断。
