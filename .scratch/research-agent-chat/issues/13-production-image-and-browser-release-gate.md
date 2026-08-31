# 13 — Production image and browser release gate

**What to build:** 用最终 Production Images 和真实浏览器证明完整 ThesisTrace Chat 产品：Caddy 单一入口、私有 Agent Host、系统 Model Registry、Better Auth、短期 OAuth、动态 MCP、Mastra、CopilotKit/AG-UI/A2UI、真实 Workers 与独立 Chat/Research 生命周期共同通过可复现 Release Gate。

**Blocked by:** 09 — Same-session concurrency and restart recovery; 12 — Real-model Eval and execution bounds

**Status:** ready-for-agent

- [ ] 最终 Compose 包含 Web/Caddy、Auth、Agent Initializer、Agent Host、Core Initializer/API、Research/Batch/Tracking Workers、PostgreSQL 和 RustFS；只有 Caddy 绑定 Host 端口，Agent Host 与私有 Health/Internal 路径不可公开访问。
- [ ] 最终 Images 使用与测试相同的精确 CopilotKit、AG-UI、A2UI、Mastra、Provider、Storage、Better Auth 和 MCP 版本，不依赖源码 Checkout、Prototype Server、开发 Volume 或运行时 Package Install。
- [ ] Production Configuration 对 Agent Schema、Model Registry、Provider Secret、Auth Exchange、Issuer/Audience、Core Verifier、MCP Policy、Route Origin/Host 与 Token/Run Lifetime 关系全部失败关闭；不存在 Disabled-auth、Anonymous 或 Alternate Backend Fallback。
- [ ] Production Image Smoke 在独立 Compose Project、Network、Volumes、Database、Accounts 和 Fixture Data 中，通过 Caddy 完成 Login、`/chat`、Model Selection、首条 Session、Scripted Fake Model、OAuth Exchange、MCP Discovery、ResearchRun Admission、Worker Terminal Result 与 A2UI Replay。
- [ ] Smoke 在有界节点验证 Research Batch 和 DailyTrack 的安全 Agent 能力，并证明 Cancel/Stop Tools 不可发现、Browser 不直接执行 Core Mutation、Agent Host 不持有 Core 私有 Credential。
- [ ] Smoke 覆盖 AG-UI Disconnect、Agent Host Graceful Restart、同一 Session Replay、同 Thread 重复 Turn 防护和已 Admission Core Resource 的独立继续执行；所有等待使用有 Timeout 的状态轮询。
- [ ] Smoke 创建一个由 Chat 产生并引用的 ResearchRun，随后删除 Chat Session，证明 Agent Content 消失而 Core ResearchRun、Result 和相关 Tracking/Batch Product State 保持不变。
- [ ] Startup、Health、Success、Failure、Restart 和 Delete 全程通过 Content Canary 扫描；证据中不存在 Message、Prompt、A2UI、Formula、Hypothesis、MCP Payload、Cookie、Token、Provider Secret、SQL、Path 或 Storage Key。
- [ ] 真实 In-app Browser 在 Expanded Desktop、Collapsed Desktop、Tablet 和 Mobile 验收 Workspace 链接顶部位置、Session History、Header、Model/Reasoning、Composer、Streaming、Tool Activity、A2UI、Delete Decision 和 Research Navigation。
- [ ] Browser 验收同时覆盖 Keyboard-only、Focus Restoration、Screen-reader Labels、Touch Targets、Contrast、Reduced Motion、Status Text、无页面级横向溢出及 Auth/Agent/Core 不可用状态。
- [ ] 完整确定性 Unit、Contract、Integration、Browser、Architecture 与 Production Image Smoke Gate 从已提交实现可用一个本地 Release 命令复现；真实模型 Eval 保留为独立、已通过且与当前版本匹配的发布证据。
- [ ] 任一 Flaky、重跑后才通过、源码通过但 Image 失败、真实模型阈值未达标或 Canary 泄漏均阻止完成；失败保存经净化的 Trace/Run ID、Dependency State、Exit Code、Seed、Screenshot 和 Image Digest。
- [ ] 本票只形成可部署与可验收证据，不执行公共 DNS、WAF、Cloudflare、生产数据迁移、Provider 采购或真实生产流量切换。
