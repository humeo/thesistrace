# 06 — Validated A2UI research surfaces

**What to build:** 让 Agent 在现有文本与 Tool Activity 之外直接生成经过验证、可持久重放的 A2UI，用标准 Primitives 和 ThesisTrace 领域组件展示 Alpha Proposal、Formula、ResearchRun、指标、结果与 Provenance，同时把浏览器交互严格限制为导航、展开和复制。

**Blocked by:** 04 — Idea-to-ResearchRun loop

**Status:** ready-for-agent

- [ ] 锁定一个受支持的 A2UI 协议与 Renderer 版本，通过 AG-UI 传输声明式 UI Event；不新增自定义并行 SSE、HTML Transcript 或只适配固定 Alpha Card 的临时协议。
- [ ] 注册经过审查的标准 A2UI Primitives，并提供 ThesisTrace Formula、Alpha Proposal、ResearchRun Status、Result Metrics、Table、Provenance 与 Navigation 组件；组件名称、Props 和 Child 关系均有明确 Schema。
- [ ] Alpha Proposal 能表达 Hypothesis、Formula、Universe、Period、Research Type、Strategy 参数与解释，但保持 Chat-owned A2UI，而不是 Core Entity、Research Draft 或 ResearchRun 承诺。
- [ ] ResearchRun 组件从真实 Tool Result 展示安全 ID、生命周期、Formula、关键指标、Result Section 和 Provenance，并明确指向权威 ResearchRun 页面。
- [ ] 浏览器只允许同源已知产品路由 Navigation、本地 Expand/Collapse 和 Copy；所有 Submit、Retry、Cancel、Stop、Delete、通用 Fetch、外部 URL 与自定义事件均被 Schema 或 Action Policy 拒绝。
- [ ] Renderer 不接受 Raw HTML、CSS、JavaScript、Iframe、任意 React Source、外部图片或 Model-authored Network Request；普通 Assistant Markdown 同样经过净化且不执行 HTML。
- [ ] 未知 Component、非法 Props、过深嵌套、过大 Payload、不安全 URL、Disallowed Action 和不完整 Event 产生稳定安全的 UI Error，不崩溃 Conversation、不执行部分动作，也不静默回退成任意 HTML。
- [ ] 验证后的 A2UI Payload 与所属 Message/Thread 一起持久化；刷新、重连或 Agent Host 重启后重放相同 UI，不再次调用模型生成。
- [ ] Tool Arguments 和完整 Tool Results 不自动展开到 UI；领域组件只接收显示所需的 owner-authorized、bounded、product-semantic 数据。
- [ ] 组件遵循现有暗色 Surface Ladder、Hairline、Mono Formula、紧凑指标和表格规则；不使用营销式大卡、渐变、Glow、Color-only Status 或嵌套装饰卡。
- [ ] 所有可交互组件具备语义名称、键盘操作、可见 Focus、触控尺寸、Reduced Motion 和错误文本；大型表格在窄屏保留每个字段含义且不造成页面级横向溢出。
- [ ] 通过真实 Chat-to-ResearchRun 闭环验证 Proposal、运行状态、完成 Result、Navigation、Copy、Expand、持久重放和安全拒绝；组件契约测试覆盖每个注册组件和 Action。
