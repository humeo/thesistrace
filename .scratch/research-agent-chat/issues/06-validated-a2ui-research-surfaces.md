# 06 — Validated A2UI research surfaces

**What to build:** 让 Agent 在现有文本与 Tool Activity 之外直接生成经过验证、可持久重放的 A2UI，用标准 Primitives 和 ThesisTrace 领域组件展示 Alpha Proposal、Formula、ResearchRun、指标、结果与 Provenance，同时把浏览器交互严格限制为导航、展开和复制。

**Blocked by:** 04 — Idea-to-ResearchRun loop

**Status:** complete

## Implementation Plan

1. Pin the supported stack at the existing CopilotKit release line: use
   `@copilotkit/a2ui-renderer@1.69.3`, its A2UI v0.9 activity contract, and the
   existing AG-UI transport. Add a shared, dependency-free product contract
   under `contracts/` containing the catalog ID, exact component/prop/child
   schemas, payload limits, safe same-origin route parser, and deterministic
   safe-error surface. Both Agent Host and Web validate against this contract;
   there is no alternate SSE, HTML, fixed-card, or compatibility path.
2. Register a deliberately small catalog: `Text`, `Row`, `Column`, `Divider`,
   `Formula`, `AlphaProposal`, `ResearchRunStatus`, `ResultMetrics`, `Table`,
   `Provenance`, and `Navigation`. Keep all displayed values literal and
   bounded. Reject unknown/extra props, unresolved or cyclic children, multiple
   parents, depth/component/payload limits, raw HTML/CSS/JS/React/iframe/media,
   function calls, network requests, and model-authored actions. Copy and
   expand/collapse remain local renderer behavior; Navigation accepts only the
   enumerated same-origin product routes.
3. Register the Mastra bridge's documented fixed-schema `render_a2ui` path on
   the main Agent and configure CopilotRuntime's version-pinned catalog and
   lifecycle middleware. This direct path is required because the pinned
   framework's subagent `generate_a2ui` path intentionally omits `changes` from
   create prompts and therefore cannot reliably carry fresh MCP facts. Let only
   the A2UI Tool events pass through the inner MCP projector so middleware can
   consume them; the final Durable Runner drops those raw Tool events and all
   progressive Activities derived from partial Tool arguments. Only a correlated,
   final server Tool result can produce a validated `a2ui-surface` Activity;
   rejected or incomplete calls produce a stable safe-error Activity. There is
   no parallel generator or fallback path.
4. Add `agent.a2ui_message`, owned by Chat Session and Agent Run, keyed by its
   AG-UI Activity message ID and carrying the validated catalog version,
   lifecycle state, bounded content, and deterministic sequence. Persist each
   accepted snapshot before emission, with an explicit per-Run sequence and a
   foreign key to its owning Assistant Message. Enable Mastra's native
   `savePerStep` so completed tool steps are durable during later long MCP calls;
   a held-MCP regression proves this without waiting for the Agent Turn to end.
   Wait for Mastra's owner commit
   before saving the Activity; load Messages and Activities in one repeatable-read
   snapshot so reconnect cannot observe an orphan or reorder timestamp ties.
   Replace incomplete terminal surfaces with a safe error and merge stored
   Activities with durable Mastra Messages on connect/duplicate replay. Session
   deletion cascades only Agent-owned rows; ResearchRun/Result/DailyTrack remain
   independent.
5. Render Activities in the existing headless Chat timeline with CopilotKit's
   official A2UI renderer and a custom React catalog. Domain renderers expose
   proposal, formula, real ResearchRun state/result/provenance, compact metrics,
   accessible responsive tables, and authoritative ResearchRun navigation.
   Suppress all renderer-to-Agent actions; implement copy and disclosure
   locally and validate Navigation immediately before use. Style the surfaces
   against `DESIGN.md` tokens, focus/touch/reduced-motion rules, and never fall
   back to arbitrary HTML. Keep Column children content-sized; the wrapping
   180-pixel basis belongs only to Row. Verify collapsed controls stay compact
   and reach them using bounded Tab traversal, never programmatic focus.
6. Extend the deterministic scripted model and full local Chat-to-Core fixture
   to emit proposal, running, and completed-result surfaces derived from real
   MCP results. Add shared contract corpus tests, Agent event/persistence/replay
   and PostgreSQL restart tests, Web renderer interaction/accessibility/narrow
   layout tests, and real Caddy E2E coverage for keyboard navigation, copy,
   expand, visible focus, mobile touch targets, 100-row/12-column labeled tables,
   replay, and malicious/invalid payload rejection. A controlled real Worker
   barrier proves the running surface without relying on timing or sleeps.
   Silence content-bearing Mastra framework logging through its native
   `noopLogger`, with real runtime log-canary regressions for strict A2UI input
   rejection rather than an expanding error-message denylist.

- [x] 锁定一个受支持的 A2UI 协议与 Renderer 版本，通过 AG-UI 传输声明式 UI Event；不新增自定义并行 SSE、HTML Transcript 或只适配固定 Alpha Card 的临时协议。
- [x] 注册经过审查的标准 A2UI Primitives，并提供 ThesisTrace Formula、Alpha Proposal、ResearchRun Status、Result Metrics、Table、Provenance 与 Navigation 组件；组件名称、Props 和 Child 关系均有明确 Schema。
- [x] Alpha Proposal 能表达 Hypothesis、Formula、Universe、Period、Research Type、Strategy 参数与解释，但保持 Chat-owned A2UI，而不是 Core Entity、Research Draft 或 ResearchRun 承诺。
- [x] ResearchRun 组件从真实 Tool Result 展示安全 ID、生命周期、Formula、关键指标、Result Section 和 Provenance，并明确指向权威 ResearchRun 页面。
- [x] 浏览器只允许同源已知产品路由 Navigation、本地 Expand/Collapse 和 Copy；所有 Submit、Retry、Cancel、Stop、Delete、通用 Fetch、外部 URL 与自定义事件均被 Schema 或 Action Policy 拒绝。
- [x] Renderer 不接受 Raw HTML、CSS、JavaScript、Iframe、任意 React Source、外部图片或 Model-authored Network Request；普通 Assistant Markdown 同样经过净化且不执行 HTML。
- [x] 未知 Component、非法 Props、过深嵌套、过大 Payload、不安全 URL、Disallowed Action 和不完整 Event 产生稳定安全的 UI Error，不崩溃 Conversation、不执行部分动作，也不静默回退成任意 HTML。
- [x] 验证后的 A2UI Payload 与所属 Message/Thread 一起持久化；刷新、重连或 Agent Host 重启后重放相同 UI，不再次调用模型生成。
- [x] Tool Arguments 和完整 Tool Results 不自动展开到 UI；领域组件只接收显示所需的 owner-authorized、bounded、product-semantic 数据。
- [x] 组件遵循现有暗色 Surface Ladder、Hairline、Mono Formula、紧凑指标和表格规则；不使用营销式大卡、渐变、Glow、Color-only Status 或嵌套装饰卡。
- [x] 所有可交互组件具备语义名称、键盘操作、可见 Focus、触控尺寸、Reduced Motion 和错误文本；大型表格在窄屏保留每个字段含义且不造成页面级横向溢出。
- [x] 通过真实 Chat-to-ResearchRun 闭环验证 Proposal、运行状态、完成 Result、Navigation、Copy、Expand、持久重放和安全拒绝；组件契约测试覆盖每个注册组件和 Action。

## Verification and Review

- Standards and Spec independently re-reviewed the identical staged patch
  `8f57e09758ac44b4bbda969ea592a4d7f8e6686e0b6a1026030dc5dfbeb4b076`
  from fixed base `5a59b2cb698ce6d64b40c170de66329a49c90660`; both final
  reports returned zero findings before this tracker-only completion update.
- Review fixes closed partial-input rendering, orphan ownership, timestamp-tie
  ordering, invented display values, missing running-state evidence, mobile
  table semantics, inflated Column layouts, programmatic keyboard focus, and
  raw framework validation logging. No compatibility path or extra workflow
  was introduced.
- Root regression baseline: Ruff and Python `917 passed`, Agent `236 passed`,
  Auth `163 passed`, Web `156 passed`, with every TypeScript check passing.
  Affected Agent/Web suites and typechecks were rerun after the functional
  fixes; final real Agent PostgreSQL acceptance was `32 passed` in isolated
  run `20260830t194929z-24407-8076357b`.
- Native Mastra `savePerStep` was proven by a red/green held-MCP regression:
  completed surfaces and their Assistant owner are durable before a later MCP
  call finishes. Strict-input log canaries were also proven red/green for
  unknown top-level fields and non-empty data. Restart, sequence, owner FK,
  repeatable-read replay, full-bound payloads, and independent deletion pass.
- Production-image browser run `20260830t195059z-25014-eadb7d83` passed all six
  selected scenarios: three unsafe-input variants; real controlled Worker
  running/result, keyboard-only Tab, copy, disclosure and Navigation; a
  100-row/12-column table at 320 pixels with replay; and Core artifact
  independence after Chat deletion. Containers and isolated volumes were
  cleaned by the test harness.
- In-app Browser independently completed a Fixture-backed Chat-to-ResearchRun
  using a separate synthetic account. Navigation measured 44 pixels inside a
  60-pixel content-sized wrapper; the 390-pixel result table retained Metric /
  Value headers and had no page-level horizontal overflow. Saved browser
  evidence is under the run's `evidence/playwright-report/` directory.
- Production Web build and budget passed: `11` assets, `1,652,001` total bytes,
  `1,577,411` JavaScript bytes. `git diff --check` passed.
