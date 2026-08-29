# 07 — Research Batch through Chat

**What to build:** 让 Researcher 在 Chat 中要求比较多个 Alpha 或 Strategy 配置时，Mastra 使用同一个动态 MCP Tool 集提交并监控 Research Batch，通过 A2UI 展示有序进度和 Child ResearchRun 结果；Agent Host 不增加 Batch 专用 Planner、聚合结果或取消路径。

**Blocked by:** 06 — Validated A2UI research surfaces

**Status:** ready-for-agent

- [ ] Scripted Fake Model 轨迹把一个自然语言比较请求转为当前 MCP Schema 支持的 Factor Evaluation Batch 或 Strategy Sweep，而不是让浏览器构造 Batch Command。
- [ ] Agent 可调用 Discovery 返回的 Batch Submit、List 和 Detail Tools，并通过 Child ResearchRun Tools 读取各 Item Result；Host 不硬编码 Tool 名称、Batch Item Schema 或 Tool 顺序。
- [ ] Agent 根据对话和 MCP Context 选择共同 Folder、日期、Universe、Neutralization、Alpha 及 Strategy 参数；缺失的关键比较意图由模型决定是否追问。
- [ ] Batch Admission 的 Request ID 与每个 Item Key 在重试、响应丢失和同一 Agent Run 内保持稳定；重复提交重放同一 Batch，不产生重复 Child ResearchRun。
- [ ] Agent 根据 Tool Guidance 自主轮询 Batch 及所需 Child Runs，并能解释 Queued、Running、Partial、Succeeded、Failed 和结构化 Admission Rejection；Host 不创建 Batch Watcher 或 Synthetic Batch Result。
- [ ] A2UI Batch Surface 展示 Batch ID、比较目标、有序 Item、进度、状态、关键结果和前往各权威 ResearchRun 的 Navigation，不显示 Manifest、Object Key、Checkpoint 或内部 Worker 状态。
- [ ] Built-in Agent 的 OAuth Grant 不包含 Research Cancel Scope，因此 Batch Cancel Tool 不可发现；页面没有 Batch Cancel 或 Confirm Action，伪造调用仍由 Core 拒绝。
- [ ] Chat Session 与 Batch 保持独立；删除或重命名 Chat 不改变 Batch、Child ResearchRun 或 Result，Core 状态变化也不改写历史 Message。
- [ ] 使用真实 PostgreSQL、RustFS、Batch Research Worker 与 Fixture Data 验证 Factor Batch 和 Strategy Sweep 从 Admission 到终态，并断言顺序、Child Identity、Result 与 Existing Core Invariants。
- [ ] 覆盖边界 Cardinality、Duplicate Item Key、Admission Rejection、Partial Child Failure、MCP Disconnect、Agent Run Bound、Idempotent Replay 和 Result Pagination；测试不逐字断言模型输出。
- [ ] 完成后可从一个真实浏览器 Session 演示“比较多个 Alpha”到 Batch 结果解释的闭环，且实现只新增通用 Agent/MCP/A2UI 组合，不复制 Core Batch 业务规则。
