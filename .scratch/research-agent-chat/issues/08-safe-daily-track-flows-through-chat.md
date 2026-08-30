# 08 — Safe DailyTrack flows through Chat

**What to build:** 让 Researcher 在 Chat 中要求持续跟踪一个成功 Strategy 时，Agent 使用当前 Discovery 返回的安全 DailyTrack Tools 完成 Start、状态读取、结果解释，以及在合法情况下的 Refresh 或 Retry；Stop 始终因 Scope 缺失而不可见。

**Blocked by:** 06 — Validated A2UI research surfaces

**Status:** complete

- [x] Scripted Fake Model 从自然语言请求或当前 Thread 中的 Strategy ResearchRun ID 开始，通过 MCP 验证 Origin Run 并提交一个幂等 DailyTrack Start。
- [x] Agent 使用当前 Discovery 返回的 DailyTrack List、Detail、Result 及所有 `tracking:execute` 安全动作；Host 不维护固定 Tool 名称清单，因此 Core 新增或移除授权 Tool 时以下一次 Discovery 为准。
- [x] 对当前合约支持的 Refresh 和 Blocked Retry，Agent 依据 Tool Description、Lifecycle 和结构化结果决定是否合法、是否调用以及是否继续轮询；Host 不实现 Refresh/Retry 状态机或调度器。
- [x] Start、Refresh 与 Retry 使用稳定 Request ID；Transport Retry、响应丢失、并发重放和 Host 重连不会创建第二个 Track 或重复同一业务动作。
- [x] A2UI DailyTrack Surface 展示 Track ID、Origin ResearchRun、状态、Data Through Session、Block Reason、最新 Observation、关键指标、Provenance 和前往权威 DailyTrack 页面的 Navigation。
- [x] Agent 能解释 Active、Blocked、Refreshing、Succeeded-like current output 及结构化失败，不把 mutable observations 描述成新的 immutable Research Result，也不暴露 Checkpoint、Lease 或 Storage Key。
- [x] Built-in Agent Grant 不包含 `tracking:stop`，因此 Stop Tool 不出现在 Discovery，页面不渲染 Stop/Confirm Action，伪造或陈旧调用仍由 Core 拒绝且 Product State 不变。
- [x] Chat 生命周期不拥有 DailyTrack；Agent Run 结束、Chat 删除、Stream Disconnect 或模型失败不停止已经存在的 Track 或其后续 Worker Advances。
- [x] 使用真实 PostgreSQL、RustFS、Tracking Worker 和 Fixture Data 验证合法 Start、已存在 Track、Active Refresh、Blocked Retry、非法 Lifecycle、依赖暂时不可用、Idempotent Replay 和 Result 读取。
- [x] 在完成 ResearchRun、Research Batch 和 DailyTrack 切片后，契约测试证明 Agent Host 对当前四个授权 Scope 的整个 Discovery 结果零遗漏直传 Mastra，并且没有 Host 级 Partial/Full Tool 模式。
- [x] 真实浏览器可以演示从 Strategy 结果到 DailyTrack 状态与 Observation 解释的闭环；测试以 Core 资源和可见行为为断言，不依赖模型逐字内容。

## Implementation plan

1. 以当前 Core MCP Discovery / DailyTrack Lifecycle 为唯一业务契约。领域中的 DailyTrack Refresh 是显式排队 Tracking Advance 的写命令，当前 Discovery 没有暴露该命令。本切片只支持重新读取 Active Track 当前视图（Detail / Result），不能把页面 Reload 描述为 DailyTrack Refresh；现有 Tracking Worker 独立推进。不添加 Refresh API、Host 调度器、Tool 白名单或 Partial/Full 模式。当前可见写工具只有 Start / Retry 需要 Request ID，Stop 仍由独立 Scope 隔离。
2. 在 test-only Scripted Model 中增加 Start、List、当前视图 Reload、Blocked Retry、显式恢复轨迹。验证 Thread 中或自然语言指定的 succeeded Strategy Origin；优先识别已存在 Track；对未知效果复用原命令，对结构化失败保留含义并有界结束。生产 Mastra 只增加 DailyTrack 语义指导，继续直传全部 Discovery。
3. 用现有 A2UI Text / Table / ResultMetrics / Provenance / Navigation 组合 Track 状态、Origin、数据日期、Block Reason、最新已发布 Observation 与指标；不增加业务专用协议或浏览器写工具。冻结历史 Surface，重新读取当前视图时生成新 Surface。
4. 添加确定性轨迹与真实 Agent PostgreSQL 持久化测试，覆盖合法/非法状态、重复 Origin、稳定 Start/Retry 重放、暂时错误、分页与不完整结果、缺失/新增 Discovery。复用现有真实 Core PostgreSQL/RustFS/Tracking Worker 契约测试覆盖并发、崩溃与动作收据。
5. 最终镜像真实浏览器验收 Strategy → Track → 当前 Observation；验证只走 Agent MCP、读取刷新、独立生命周期、响应丢失恢复、导航与窄屏。按范围运行静态/单元/集成/镜像测试；相同暂存 SHA256 上独立 Standards + Spec 审查，修复后复审，更新 tracker 并单独提交。

## Verification and review

- Current Core Discovery does not expose DailyTrack Refresh. The conditional
  Refresh criteria above therefore apply only to capabilities actually
  discovered: Start and Retry carry stable request IDs; Reload reads the current
  view and is not an effectful Refresh command. Queued/calculating/retry-wait
  phases are interpreted from Core, not a fabricated `refreshing` Track status.
- Standards and Spec independently re-reviewed staged patch
  `18661a2077ecfce552437db8db7e44f56165d58bac5064f0f99165908adc90f2`
  from fixed base `1f66c5a18feb46fe742768eae3edea370008cd18`.
  Standards' two initial findings (Refresh terminology and unbounded test child
  processes) were fixed; final Standards and Spec each report zero findings.
  Both reviewers independently passed the 39 DailyTrack and 12 A2UI contract
  cases. This completion entry is the only post-review tracker update.
- Deterministic baseline passed Ruff, Python `917`, Agent `297`, Auth `163`,
  Web `157`, and Agent/Web typechecks. After the final terminology and timeout
  fixes, focused `51` cases and both typechecks passed again.
- Full isolated integration run `20260830t210032z-55683-0a71ddfc` passed Core
  `370` cases plus all `6` PostgreSQL/RustFS restart cases, followed by Auth
  `89` and Agent PostgreSQL `36` cases. Core coverage includes concurrent
  Start/Retry, duplicate Origin, illegal lifecycle, transient dependencies,
  missing Stop scope, persisted receipts and bounded Result pagination.
  The native Mastra test also proves all 15 currently granted MCP capabilities
  reach the model, including removal/addition on the next Discovery.
- Final Production Image browser run `20260830t211143z-71969-c62d45b1` passed
  all `3` selected scenarios: real Strategy-to-DailyTrack current results,
  lost Start/Retry response recovery, and the existing Batch response-loss
  regression. Stable receipts and resource IDs prove no duplicate effects.
  After Chat deletion a real Tracking Worker advances the surviving Track
  from the fixed Origin to Dataset Head. Browser writes stay on Agent MCP;
  Stop is neither discovered nor invoked.
- Desktop and 390px screenshots were inspected from that run's
  `evidence/playwright-report/data/` directory; current metrics, Observation,
  provenance and canonical DailyTrack navigation render without horizontal
  overflow. Historical A2UI snapshots remain unchanged on reload/restart.
- The initial image run exposed a test setup error: a local one-shot Worker
  lacked the required internal API origin. The corrected fault setup uses
  the production Worker entrypoint inside the isolated API image, with a
  60-second timeout. The failed attempt is not counted as passing evidence.
- Final Web image contains `11` assets / `1,652,049` total bytes /
  `1,577,459` JavaScript bytes. `git diff --check` passed. Isolated harnesses
  report zero cleanup/secret-cleanup failures; development data was untouched.
