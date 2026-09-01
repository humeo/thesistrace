# 04 — Idea-to-ResearchRun loop

**What to build:** 让 Researcher 用一句自然语言 Alpha 想法驱动 Mastra Agent 自主读取研究上下文、选择 Research Folder、查询 Catalog、诊断或修正 Formula、提交 ResearchRun、按 Tool Guidance 轮询并解释真实 Result；整个闭环不需要用户手写完整 Alpha 程序或确认按钮。

**Blocked by:** 03 — OAuth-protected MCP read turn

**Status:** complete

## Implementation Plan

1. Keep the production orchestration boundary as one Mastra Agent with the
   complete per-Run MCP discovery. Make its deployed instructions explicit
   about reliable platform defaults, model-owned Tool choice and polling,
   structured correction, authoritative Result claims, and caller-stable
   effect IDs derived by the model from the current Agent Run identity. Raise
   only the fixed Mastra step bound needed for the measured six-Tool research
   loop; add no Host poller, planner, Folder selector, continuation record, or
   business Tool inventory.
2. Extend the registered Scripted Fake Model—not the Agent Host runner—with
   deterministic natural-language Factor Evaluation and Strategy Backtest
   trajectories. The fake model will inspect the currently supplied function
   Tools and model-visible Tool results, read Research Context, query the Alpha
   Catalog, diagnose its own Formula, choose Folder and bounded defaults,
   submit, follow lifecycle guidance, select a compatible Result section, and
   generate compact Markdown from the observed authoritative result.
3. Make the fake model's state entirely reconstructible from current-thread
   model history. Derive one effect Request ID from the Agent Run identity,
   reuse the exact Tool name, arguments, and Request ID after a transient or
   uncertain response, and allocate a new revision only after a structured
   rejection changes the command. This preserves Core as the idempotency
   authority and allows a later Agent Run to retry an interrupted admission
   from durable Tool history without a Host workflow table.
4. Honor only model-visible `retry_after_seconds` guidance before the fake
   model chooses the corresponding retry or poll. The wait is abortable,
   bounded by the existing total Agent Run wall time and fixed step limit, and
   injectable as a virtual delay in deterministic tests. Terminal failure,
   no useful Result section, or exhausted bounds yields an explicit response;
   it never starts a background watcher or mutates the admitted ResearchRun.
5. Replace the browser Tool terminal string with one versioned, strictly
   validated safe marker. Project only lifecycle outcome plus a public
   ResearchRun identifier and status when those exact bounded fields can be
   validated from the Core result. Apply the same projection to live events,
   durable replay, reconnect snapshots, and browser transcript validation;
   continue removing arguments, full results, diagnostics, and internal IDs.
6. Extend the fixed Tool Activity renderer to show the safe ResearchRun ID,
   Core status, and an exact same-origin `/research-runs/<id>` navigation link.
   Render assistant output with a directly pinned streaming Markdown renderer,
   disabled controls/images/raw HTML, an allowlisted internal-link component,
   and product mono treatment for Formulae and identifiers. Keep the browser
   free of approval, Confirm-and-run, and direct Core mutation controls.
7. Add deterministic provider tests for direct Factor and Strategy paths,
   invalid Formula repair, structured admission revision, transient guidance,
   stable retry arguments, compatible Result selection, terminal worker
   failure, materially ambiguous follow-up, and bounded early return. Assert
   Tool choices and artifacts rather than exact prose.
8. Add real Agent-boundary PostgreSQL tests with scripted MCP Tools for the
   complete step sequence, safe event projection and replay, response-loss
   recovery with the same Request ID, business rejection versus transport
   failure semantics, disconnect/timeout termination, and the absence of any
   Host-side workflow state.
9. Extend the authenticated Caddy browser seam so the Scripted Fake Model
   creates both a Factor Evaluation and a Strategy Backtest through the real
   OAuth-protected Core MCP, PostgreSQL, RustFS, Canonical Fixture, and Research
   Worker. Use timeout-bounded condition polling and assert the frozen input,
   pinned Data Generation, ownership, terminal Result, visible safe ID/status,
   Markdown fields, reload replay, and navigation—not exact assistant wording.
10. Reuse and extend the existing Core MCP protocol, deterministic trajectory,
    admission/idempotency, lifecycle failure, and Result tests for Formula
    correction, Admission Rejection, Worker Failure, transient backoff, early
    Agent termination, and same-Request-ID replay. Do not duplicate Core's
    lifecycle implementation inside Agent tests.
11. Run affected tests first, then all repository unit, integration, browser,
    Compose, and production-image gates. Review the fixed-base diff separately
    for repository Standards and this ticket's Spec, fix every finding, rerun
    affected acceptance, re-review to zero findings, mark only Issue 04
    complete, and create its independent conventional commit.

- [x] 确定性 Scripted Fake Model 轨迹从自然语言 Idea 开始，使用当前动态 Discovery 中的 Context、Catalog、Diagnostics、ResearchRun Admission、Detail 和 Result Tools 完成一个 Factor Evaluation 闭环。
- [x] 同一入口也能提交并解释 Strategy Backtest；Researcher 不需要在 Chat UI 选择 Folder、日期、Universe、Neutralization 或 Strategy 参数，Agent 依据对话、MCP Context 与 Tool Schema 决策。
- [x] 足够明确的请求使用可靠平台默认值，不出现固定后端 Wizard；只有模型判断缺失意图会实质改变 Research 时才在对话中提出 Follow-up。
- [x] Agent 生成调用者稳定的 Effect Request ID；传输重试、响应丢失和相同 Tool Call 重放返回同一 Core ResearchRun，不创建重复工作或改变原 Command。
- [x] Correctable Formula Diagnostics 和 Admission Rejection 作为结构化 Tool Result 返回模型，使 Agent 可以修正并再次提交；Auth、Forbidden、Lifecycle、Transient 和 Internal Error 保持其稳定错误语义。
- [x] 研究被接受后，Tool Activity 显示安全 Run ID 与状态，Agent 自主决定是否按 `retry_after_seconds` 轮询、读取哪个 Result Section 以及何时向用户返回。
- [x] Agent Host 不实现 ResearchRun Poller、Watcher、Continuation Job、Folder Chooser、Formula State Machine 或隐藏的后台 Run；所有模型步骤受当前固定上限约束。
- [x] Agent Run 达到终态、断流或超时只停止 Agent 编排；已经被 Core 接受的 ResearchRun 继续由现有 Worker 执行，稍后的 Chat Run 可以通过 MCP 再次找到并解释它。
- [x] 普通 Markdown 与紧凑 Tool Activity 能显示生成的 Formula、假设、Research 类型、终态指标、结论及前往权威 ResearchRun 页面的安全链接；结构化 A2UI 留给后续票。
- [x] 浏览器不存在 Confirm-and-run、Approval Interrupt 或直接调用 Core Mutation 的按钮；Research 写入只从 Mastra Agent 通过 MCP 发生。
- [x] 使用真实 PostgreSQL、RustFS、Canonical Fixture 和 Research Worker 从 Admission 运行至终态；测试断言 Core Frozen Input、Data Generation、Result 和 Ownership，而不逐字断言模型回复。
- [x] 覆盖合法直接提交、Formula 修正、Admission Rejection、Worker Failure、MCP Transient Backoff、Agent Run 提前结束、Transport Reconnect 和同一 Request ID 重放，所有等待均为有 Timeout 的条件轮询。

## Verification and Review

- Standards review closed unknown-status termination, mobile Tool link target
  size, unbounded Markdown bundle growth, brittle SSE parsing, structured
  Admission correction, and precise fail-closed explanations. Final Standards
  re-review from fixed base `551aac8`: zero findings.
- Spec review verified the complete Factor and Strategy trajectories, dynamic
  MCP discovery, model-owned defaults/polling, stable effect replay, safe
  browser projection, independent Core execution, and absence of Host workflow
  state. Final Spec re-review from fixed base `551aac8`: zero findings.
- `pnpm test`: Ruff passed; Python `917 passed`; Agent `126 passed`; Auth
  `163 passed`; Web `117 passed`; all TypeScript typechecks passed.
- `pnpm test:integration`: Core `370 passed, 8 deselected`; all six restart
  suites passed; Auth `89 passed`; Agent `18 passed`. Full evidence run:
  `20260830t065205z-38242-474c1aa0`. The final structured Admission correction
  also passed the Agent PostgreSQL integration suite `18/18` in
  `20260830t071429z-68700-00dd65c5`.
- `pnpm test:e2e`: `26 passed`, including real Factor and Strategy loops,
  early Agent termination and later resume, same-Request-ID response-loss
  replay, safe Tool links, reload, and an explicit injected `503` then visible
  Retry recovery. Full evidence run: `20260830t063955z-21988-46701130`;
  focused RED/GREEN runs: `20260830t063349z-19078-845679b8` and
  `20260830t063649z-20523-feabe201`.
- `pnpm test:image-smoke`: final Core, Auth, Agent, Web, and Caddy production
  images passed, including Agent SSE/JSON safe-marker parsing, dependency and
  Worker failure recovery, resource limits, CSP, redirects, and cleanup. Runs:
  Core `20260830t071829z-81054-cf30ebc1`, Auth
  `20260830t073427z-89331-5cf3b612`, Agent
  `20260830t073459z-89572-10fe4d6d`, and Caddy
  `20260830t073607z-90301-9fe63388`.
- The production Web bundle contained `11` assets, `1,500,666` total bytes,
  and `1,441,936` JavaScript bytes, within the checked product budgets and
  without Mermaid, KaTeX, Shiki, or code-block bundles. `git diff --check`:
  passed.
