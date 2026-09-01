# 13 — Production image and browser release gate

**What to build:** 用最终 Production Images 和真实浏览器证明完整 ThesisTrace Chat 产品：Caddy 单一入口、私有 Agent Host、系统 Model Registry、Better Auth、短期 OAuth、动态 MCP、Mastra、CopilotKit/AG-UI/A2UI、真实 Workers 与独立 Chat/Research 生命周期共同通过可复现 Release Gate。

**Blocked by:** 09 — Same-session concurrency and restart recovery; 12 — Real-model Eval and execution bounds

**Status:** complete

## Implementation plan

1. Treat the release seam as the existing final-image `e2e` environment plus
   the lower-level `image-smoke` suites: the browser gate owns the complete
   Caddy -> Auth -> Agent -> OAuth -> MCP -> Workers -> Result loop, while the
   image suites retain startup, schema, container-boundary and Caddy/TLS
   checks. Do not duplicate the already accepted Issue 06-11 journeys.
2. Add a committed-HEAD release entrypoint that refuses a dirty tracked or
   untracked worktree, then runs the deterministic unit, architecture,
   integration, final-image browser and image-smoke gates. It must explicitly
   exclude the paid real-model Eval and preserve the Issue 12 qualification
   waiver: no release result may describe the model as qualification-passed.
3. Close remaining final-image and fail-closed configuration gaps with contract
   tests first. Recheck the exact package/runtime pins, Caddy-only production
   publication, Agent/Core credential separation, destructive Tool absence,
   bounded waits, sanitized failure evidence and the earlier isolated RustFS
   startup incident before changing implementation.
4. Run the smallest deterministic suites while editing, then the frozen full
   gate. Use an isolated Compose project, volumes, database, accounts and
   fixtures; never touch `thesistrace-dev` or its data.
5. On the final local image stack, independently inspect Expanded Desktop,
   Collapsed Desktop, Tablet and Mobile with the real In-app Browser, including
   workspace-link placement, model/reasoning controls, session lifecycle,
   streaming/Tool/A2UI states, deletion wording, Research navigation and the
   required accessibility/unavailable states.
6. Freeze the patch, obtain independent Standards and Spec reviews, fix every
   finding, re-review the identical staged tree, update this tracker, commit
   Issue 13 alone, and execute the committed-HEAD release entrypoint. Any
   flaky/rerun-only result, image failure or Canary leak keeps the issue open.

The explicit Issue 12 user waiver applies here as well: the 33-attempt
qualification is not part of this deterministic release run, remains pending,
and is never represented as passed evidence.

- [x] 最终 Compose 包含 Web/Caddy、Auth、Agent Initializer、Agent Host、Core Initializer/API、Research/Batch/Tracking Workers、PostgreSQL 和 RustFS；只有 Caddy 绑定 Host 端口，Agent Host 与私有 Health/Internal 路径不可公开访问。
- [x] 最终 Images 使用与测试相同的精确 CopilotKit、AG-UI、A2UI、Mastra、Provider、Storage、Better Auth 和 MCP 版本，不依赖源码 Checkout、Prototype Server、开发 Volume 或运行时 Package Install。
- [x] Production Configuration 对 Agent Schema、Model Registry、Provider Secret、Auth Exchange、Issuer/Audience、Core Verifier、MCP Policy、Route Origin/Host 与 Token/Run Lifetime 关系全部失败关闭；不存在 Disabled-auth、Anonymous 或 Alternate Backend Fallback。
- [x] Production Image Smoke 在独立 Compose Project、Network、Volumes、Database、Accounts 和 Fixture Data 中，通过 Caddy 完成 Login、`/chat`、Model Selection、首条 Session、Scripted Fake Model、OAuth Exchange、MCP Discovery、ResearchRun Admission、Worker Terminal Result 与 A2UI Replay。
- [x] Smoke 在有界节点验证 Research Batch 和 DailyTrack 的安全 Agent 能力，并证明 Cancel/Stop Tools 不可发现、Browser 不直接执行 Core Mutation、Agent Host 不持有 Core 私有 Credential。
- [x] Smoke 覆盖 AG-UI Disconnect、Agent Host Graceful Restart、同一 Session Replay、同 Thread 重复 Turn 防护和已 Admission Core Resource 的独立继续执行；所有等待使用有 Timeout 的状态轮询。
- [x] Smoke 创建一个由 Chat 产生并引用的 ResearchRun，随后删除 Chat Session，证明 Agent Content 消失而 Core ResearchRun、Result 和相关 Tracking/Batch Product State 保持不变。
- [x] Startup、Health、Success、Failure、Restart 和 Delete 全程通过 Content Canary 扫描；证据中不存在 Message、Prompt、A2UI、Formula、Hypothesis、MCP Payload、Cookie、Token、Provider Secret、SQL、Path 或 Storage Key。
- [x] 真实 In-app Browser 在 Expanded Desktop、Collapsed Desktop、Tablet 和 Mobile 验收 Workspace 链接顶部位置、Session History、Header、Model/Reasoning、Composer、Streaming、Tool Activity、A2UI、Delete Decision 和 Research Navigation。
- [x] Browser 验收同时覆盖 Keyboard-only、Focus Restoration、Screen-reader Labels、Touch Targets、Contrast、Reduced Motion、Status Text、无页面级横向溢出及 Auth/Agent/Core 不可用状态。
- [x] 完整确定性 Unit、Contract、Integration、Browser、Architecture 与 Production Image Smoke Gate 从已提交实现可用一个本地 Release 命令复现；真实模型 Eval 保持独立，本次按用户明确豁免不执行 qualification，也不宣称已通过或与当前版本匹配。
- [x] 任一 Flaky、重跑后才通过、源码通过但 Image 失败或 Canary 泄漏均阻止完成；若执行真实模型门禁，阈值未达标只阻止 qualification/release claim，当前豁免不把待定状态改写为通过；失败保存经净化的 Trace/Run ID、Dependency State、Exit Code、Seed、Screenshot 和 Image Digest。
- [x] 本票只形成可部署与可验收证据，不执行公共 DNS、WAF、Cloudflare、生产数据迁移、Provider 采购或真实生产流量切换。

## Comments

### 2026-09-01 — Deterministic final-image gate and review closure

- The full deterministic source gate passed from the frozen implementation:
  964 Python unit/architecture tests, 486 Agent tests, 11 offline Eval
  preflight tests, 163 Auth tests and 208 Web tests, with Agent/Auth/Web
  typechecks. The Release entrypoint's focused contract tests pass 3/3 and now
  prove both clean-worktree refusal and execution from the repository root.
- Production image smoke run `20260901t100512z-61340-f042a8a9` completed every
  named startup, readiness, worker-loss, restart, RustFS outage, MCP/Caddy and
  evidence phase with status `0`; secret cleanup, raw Canary scan and isolated
  Compose cleanup also returned `0`. This is supporting dirty-worktree
  evidence; the plan's clean committed-HEAD Release command runs immediately
  after this ticket commit and any failure reopens the issue.
- Final-image browser run `20260901t133300z-35113-e489219f` passed all 56 E2E
  journeys on the first execution in 919 seconds, without retry. It covered
  Auth/Core readiness failure and recovery, Agent reconnect/replay, Session
  concurrency and deletion independence, Research Batch, DailyTrack, Tool and
  A2UI journeys. Runtime-secret cleanup, raw Canary scan and isolated resource
  cleanup returned `0`. A separate Factor Batch regression and the final
  return-to-Chat image check each passed 1/1 after their respective fixes.
- Real In-app Browser acceptance used the isolated final-image stack
  `thesistrace-test-20260901t142519z-75177-9084d182`. Expanded Desktop
  (1440x1000), Collapsed Desktop (56 px sidebar), Tablet (820x1180) and Mobile
  (390x844) all had no page-level horizontal overflow. Workspace navigation
  remained above Session history; Model, Reasoning and Composer stayed visible.
  Mobile open/close/send targets were 44x44 px, Escape restored focus to Open
  navigation, and the drawer made its inactive state inert. The accessibility
  tree exposed explicit labels/status text, the tested foreground/background
  palette pairs ranged from 4.70:1 to 19.61:1, and the final stylesheet retains
  the bounded `prefers-reduced-motion` override.
- The same browser session observed `Starting run...` with the Composer
  disabled, then `Run complete`, four completed MCP Tool activities, two
  schema-rendered Research surfaces, one durable Session, and successful
  navigation to an independently succeeded ResearchRun. The Delete decision
  focused Cancel and explicitly stated that ResearchRuns, Results and Daily
  Tracks remain independent; deletion was cancelled rather than performed.
  Stopping only the isolated Agent Host produced a disabled, retryable Chat
  unavailable state; restarting it restored the same Session, replayed Tool
  state and `Run complete`.
- The diagnostic-only retained environment was cleaned by its exact
  metadata-bound Test project name. All containers, network and volumes were
  removed. Four temporary screenshots containing synthetic Chat/Formula
  content were deleted; six content-free layout/unavailable screenshots remain
  under the ignored `.local/test-runs/20260901t142519z-75177-9084d182/manual-browser/`
  directory.
- Both independent reviewers examined staged SHA-256
  `3528fe247869a11ff64a5d5a13e032ae28f18e632b5c7ac1ce0f62f4b6693442`
  against `08e4e865ee439b72f90acc4ed4f2a461ad943c89` and reported zero Standards
  findings and zero actionable Spec findings. The final repository-root test
  oracle closes the last P2; prior timeout swallowing, fixed sleep, stale
  Provider wording and unpinned sidecar findings remain closed.
- Real-model qualification is explicitly `pending/not_run`. Per the user's
  waiver, the 33-attempt qualification is not executed by this ticket or its
  Release command, and neither the Luna/high baseline nor Scripted image
  evidence is represented as qualification-passed.
