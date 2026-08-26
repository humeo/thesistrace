# 11 — 闭合固定入口边界与精确 V1 合同

**What to build:** 将完整 MCP 服务收口为一个可精确枚举、硬切、资源有界的 V1 合同，使任何 Host、scope 组合或高负载调用都只能看到获准的十八个研究 Tool 子集，并在昂贵 Core 工作开始前受到固定入口保护。

**Blocked by:** 10 — 统一结构化错误与安全运维事件

**Status:** ready-for-agent

- [ ] 精确 inventory 测试断言服务器只有 Spec 定义的 18 个 Tool、6 个 scopes、确定的 descriptions、annotations、input Schema 和 output Schema。
- [ ] 默认 stdio principal 只发现其四个安全 scopes 对应的 15 个 Tool；三个危险 Tool 仅在相应 cancel/Stop scope 明确授予时出现，调用时仍重复授权。
- [ ] 负向 contract 断言不存在 Folder mutation/delete、ResearchRun/DailyTrack delete、ResearchRun retry、Data Operator、generic SQL/Python/shell/HTTP/object Tool、Batch Result Tool、Prompt、Resource、Sampling、Elicitation、Subscription。
- [ ] HTTP 只存在一个当前 `/mcp`，不存在 versioned endpoint、legacy SSE、alias、old field、compatibility dispatcher、fallback 或 principal-supplied Tool-set override。
- [ ] 通过确定性测试和当前 production resource envelope benchmark 选择并记录固定 request bytes、response bytes、Formula size、per-principal rate、per-principal concurrency、page 与 collection 上限；这些常量不成为 V1 用户配置。
- [ ] authentication、request size、Schema、scope、rate 与 concurrency 检查在数据库、对象存储和 Worker admission 等昂贵操作前发生；Core 自身的 capacity/lifecycle admission 继续保持权威。
- [ ] 超大 request/response、Formula、page、Batch、cursor、突发 rate 与 concurrent calls 返回稳定有界失败，不产生部分资源、不截断 structured JSON，也不泄漏其他调用结果。
- [ ] 列表默认 20、最大 50，所有输出 deterministic、bounded；一个合法 item 自身无法放入响应上限时返回稳定 contract failure 而不是静默省略。
- [ ] 完整 registry、两个 transport、授权交集、边界 benchmark、并发与 forbidden-surface 测试通过，并证明没有新增 User、tenant、Workspace、quota、billing、Campaign 或 MCP session state。
