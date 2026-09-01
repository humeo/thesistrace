# 12 — Real-model Eval and execution bounds

**What to build:** 建立与确定性工程测试分离的真实模型 Eval，用固定自然语言研究语料测量每个候选注册模型与推理强度完成 ResearchRun、Research Batch、DailyTrack 和结果解释的质量、成本、延迟与方差，并用实测证据固定可发布模型和 Agent 执行上限。

**Blocked by:** 07 — Research Batch through Chat; 08 — Safe DailyTrack flows through Chat; 11 — Content-free telemetry and runtime isolation

**Status:** complete

## Implementation plan

1. Add a fixed, versioned research corpus and a closed evaluation contract.
   Each case declares its conversational inputs, required/forbidden MCP
   capabilities, independently observable Core outcomes, isolation boundary,
   repetition count and spending/time ceilings. Cover the complete accepted
   research surface, including honest handling of unavailable DailyTrack
   Refresh rather than inventing a capability or equating Reload with Refresh.
   Keep Formula repair separate from an actual Core admission-rejection repair;
   the fixed corpus has eleven cases. Baseline runs each case once for 11
   attempts and 12 primary Turns; qualification runs three repetitions for 33
   attempts and 36 primary Turns.
2. Reuse the existing isolated final-image test runtime behind an explicit
   `agent-eval` Operator command. Provision real Auth sessions, submit through
   the public Chat transport, use the real Auth exchange and Core MCP, and
   observe independent Core artifacts. Keep paid credentials in process
   environment only; default deterministic commands must not select or send
   credentials to a paid provider. Use the existing real-worker fixtures for
   polling and blocked-track recovery, not a host-side planner or fake state.
3. Produce schema-validated content-free JSON and Markdown reports using
   approved Run/Tool telemetry and artifact assertions. Record corpus,
   dataset/window, image/runtime/config fingerprints, repetitions, provider
   reasoning mapping, usage completeness, explicit pricing and failure source.
   Calculate task success, tool validity/errors/recovery, admission correction,
   cost, duration percentiles, steps and variance without persisting generated
   text or treating missing usage as zero. Repair the existing title evaluator
   to the current observation contract and keep its costs explicitly separate.
4. Any resumed baseline must use the explicitly selected registered Provider
   and model; the current user selection is the local OpenAI-compatible service
   with `gpt-5.6-luna` / `high`. The previous direct-OpenAI mini baseline proposal
   is superseded. The user has now authorized the fixed real evaluation without
   an additional spending ceiling; retain the evaluator's existing per-run
   protective budget and execution limits. Connectivity alone does not qualify
   a baseline. Pin
   reviewed qualification thresholds and startup release configuration from
   measured evidence; no scripted result, automatic model fallback or
   probabilistic retry can qualify a model.
5. Complete the execution envelope with a small fail-closed concurrent-run
   capacity at the existing runner ownership boundary, preserving reconnect,
   per-session exclusion and shutdown behavior. Verify limits at their cheapest
   reliable layer and against the final image's resource envelope; pin message,
   context, output, tool-result, step, wall-time and MCP token margin values using
   the worst accepted real trajectories and deterministic saturation evidence.
6. Run deterministic unit/contract, real PostgreSQL and isolated production
   image checks, plus the separate real-model baseline. Retain the frozen
   qualification command and thresholds, but do not treat baseline evidence as
   qualification. The user explicitly waived executing the 33-attempt
   qualification for this ticket, so the model remains unqualified while Issue
   12 may complete. Obtain independent Standards and Spec reviews of the
   identical staged SHA256, fix and re-review, then update this tracker and
   commit Issue 12 alone before starting Issue 13.

## Authorization boundary

- The latest user instruction selects `CLI_API_KEY`, the local service at
  `http://localhost:8317/v1`, and `gpt-5.6-luna` / `high`. This worktree's
  Development profile now uses that selection; the existing running Development
  services and data remain untouched. Credentials stay in process environment
  and are injected only into Agent. Containers use `host.docker.internal` to
  reach the same host service.
- The previous `api.openai.com` / mini / USD 20 baseline proposal is no longer
  active. The user's reply, “OK，没有上限”, authorized the fixed real baseline
  with no additional user-imposed spending ceiling. The completed 11-attempt,
  12-primary-Turn baseline used the selected local service and the evaluator's
  USD 100 protective ceiling. Only isolated replay data was in scope, and the
  reference-price estimates are not the local service's actual billing.
- Qualification remains an explicit Operator action with three frozen
  repetitions, but the user expressly waived that execution for Issue 12 and
  directed work to continue to Issue 13 after this issue is committed. No model
  is described as qualification-passed, and no release decision may infer that
  status from the baseline.

- [x] 建立版本化固定 Eval Corpus，覆盖清晰 Idea-to-Alpha、需要一次 Follow-up 的歧义请求、非法 Formula 修正、Strategy Backtest、Alpha 比较 Batch、DailyTrack Start/Refresh/Retry、长 Research Polling 和 Result Explanation。
- [x] 每个 Case 定义可自动判定的任务 Outcome、必需/禁止 Tool Capability、Core Artifact、权限边界和最大成本/时间输入；不以模型回复逐字匹配作为成功条件。
- [x] Eval 为每个候选 Model Key 与支持的 Reasoning Effort 固定并公开记录 baseline 与 qualification 重复次数，固定 Dataset、Clock Window、Corpus、Runtime Version 和配置；报告 Schema 包含运行间方差，实际 qualification 由本票的显式用户豁免暂缓。
- [x] 报告至少包含 Task Success Rate、Invalid/Forbidden Tool Rate、Tool Retry/Error Rate、Admission Correction Success、Token Usage、Estimated Cost、P50/P95 Duration、Agent Step Count 和 Run-to-run Variance。
- [x] Eval 使用真实 Provider、Auth Exchange、Core MCP 和 owned infrastructure，但由显式 Operator 命令启动；默认 Unit/Integration/E2E/Release Deterministic Gate 不访问付费 Provider 或把概率重试当成通过。
- [x] Eval Report 只使用上一票批准的 Metadata 与 Core Artifact 判断，排除 Prompt、Message、Formula、MCP Payload、Credential 和 Provider Raw Body；报告可安全保留和比较。
- [x] 根据第一轮 baseline 为候选 Model/Reasoning Combination 固定最低成功率、最大 Tool Error、最大 P95、最大成本和可接受方差；没有 qualification 证据的组合不得被描述为 qualification-passed，也不增加自动 Fallback。
- [x] 根据最差可接受成功轨迹与生产资源包络固定 Message Bytes、Context Tokens、Output Tokens、Tool Result Bytes、Tool Steps、Agent Run Wall Time、并发 Capacity 及 MCP Token Lifetime Margin。
- [x] Provider-specific Reasoning Mapping 经过真实调用证明；不支持或语义不等价的 Effort 不出现在 Catalog，也不转换成未披露的 Provider 参数。
- [x] Eval 能区分模型质量失败、Provider Failure、MCP Failure、Core Admission Rejection 和 Dataset/Worker Failure，避免把基础设施错误错误计算成模型能力。
- [x] Baseline 与 qualification 对同一 Runtime/Corpus 产生可比较的机器可读 Summary 和人类可读结论；阈值、模型状态和执行上限的变化需要显式 Review，不在运行时 Hot Reload。
- [x] Qualification 机制与发布门槛保持完整；本票按用户明确豁免不执行 33-attempt qualification，且不以 Scripted Fake Model 或 baseline 冒充 qualification 质量证据。

## Comments

### 2026-08-31 — Offline engineering verification; qualification still pending

- Deterministic checks passed: Ruff, 949 Python tests, 403 Agent tests, five
  offline Eval CLI preflight tests, 163 Auth tests and 204 Web shell tests;
  Agent/Auth/Web typechecks passed. The first Auth invocation was blocked by
  the execution sandbox: a minimal launch reproduced `listen EPERM` on
  `127.0.0.1`. The unchanged Auth suite passed with loopback permission. This
  was an environment correction, not a probabilistic test retry.
- Real PostgreSQL integration passed all 55 tests in isolated project
  `thesistrace-agent-test-20260831t032844z-37772-28b6bfee`, including owner-scoped
  correction facts read from native Mastra Memory and global admission
  capacity. The fixture uses the public MCP accepted-result contract
  (`run_id`), not the separate Core-internal service shape (`run.id`).
- Final-image capacity E2E passed in
  `thesistrace-test-20260831t023336z-94789-49f8af84`: four active Runs, explicit
  fifth-Run rejection without persistence, bounded container resources, and
  explicit retry of the original unaccepted message after capacity returns.
- All three final-image correction E2Es passed in
  `thesistrace-test-20260831t032841z-37591-20e0d643`: actual warmup admission
  rejection followed by one accepted fixed-window Run, plus Formula and
  admission correction measured from native Memory without exporting it.
  Earlier failures exposed the evaluator's incorrect nested accepted-result
  assumption; a failing contract test reproduced it before the fix. The
  corrected oracle accepts only the current flat MCP contract and explicitly
  rejects the internal shape. Both successful E2E runs recorded overall,
  secret cleanup, raw Canary scan and isolated resource cleanup status `0`,
  with no Canary findings. Test artifacts remain under their respective
  `.local/test-runs/` directories; no development data was used or removed.
- The previous staged-snapshot review
  (`9b5fba78f7b764417808678fced8d15b5cd0ed1467752e45c1fb6565b60dbd3f`)
  identified state-polling, failure-attribution, batch-status and model-ID
  validation issues. The implementation now releases the Worker after an
  observed nonterminal Tool result, measures ordered states for the same Run,
  preserves known failure sources when usage is unknown, recognizes Core's
  `completed_with_failures`, and reuses the registry's model-ID validator.
  Formula repair and actual admission correction have separate corpus cases
  and deterministic negative controls. A new identical-snapshot Standards and
  Spec re-review is still required.
- These results are engineering evidence only. No paid model evaluation has
  run, no real model is release-qualified, and thresholds/execution limits
  remain provisional until the separately authorized baseline and subsequent
  qualification pass. Issue 12 remains `needs-info`, uncommitted and
  incomplete; Issue 13 has not started.

### 2026-08-31 — Parallel Tool observation-order correction

- Independent reviews of staged snapshot
  `47f34c11ba49498785b40bccaafb273a35607e29edd4f3b3f6610487e1af7220`
  returned zero Standards findings and one new Spec P2: concurrent Tools may
  finish in a different order from their invocation. Traversing invocation
  order could misclassify both polling and unresolved Tool errors. The
  separate real-model qualification requirement remained explicitly pending.
- Four native AG-UI parser regressions failed before the correction, covering
  both directions of polling and error-recovery misclassification. The
  evaluator now retains start/result events in their actual observation order.
  Polling and failure attribution consume result events; retry measurement
  consumes both, excluding already-started parallel calls. Unfinished attempts
  stay visible, cross-Turn recovery remains measurable, and the latest
  unresolved capability failure keeps its actual result order. This changes
  only offline measurement, not Agent or Worker concurrency.
- The corrected event-stream suite passes all 18 tests; the full Agent suite
  passes all 409 tests and typechecking passes. The five offline CLI preflight
  tests also pass. The earlier real PostgreSQL and final-image checks above
  remain evidence for their unchanged runtime/Core boundaries; no paid
  qualification is inferred from them. A new identical-snapshot two-axis
  re-review is required before this WIP is considered engineering-reviewed.

### 2026-08-31 — Offline review closed; Provider authorization required

- Both independent axes reviewed the identical staged snapshot
  `8180df5165f1c42f70b4cb63d1ac4011fa9002f70308ad771ad1dc47c74a2060`
  against HEAD `fb6f22c8a55075caf3b2bd2a7b9107de662a6bb1`, with unchanged
  fingerprints and no unstaged edits at the start or end of either review.
  Standards reported zero hard violations and zero judgement-only smells.
  Spec reported zero remaining actionable code findings and zero scope
  expansion; the parallel-result-order P2 is closed. Each reviewer independently
  passed 37 relevant offline tests. This entry is the only change after that
  reviewed snapshot; implementation and test sources are unchanged.
- The unfinished Spec requirement is real-model qualification. No Provider
  evaluation has been executed, no model/effort is release-qualified, and the
  checked-in thresholds and capacity are still provisional. Explicit approval
  is required to send the fixed corpus, discovered MCP schemas and isolated
  research results to `api.openai.com` using
  `gpt-5.4-mini-2026-03-17` / `medium` for one 33-attempt, 36-primary-Turn
  baseline capped at USD 20. No development data is included. Baseline review
  and a separately authorized qualification run must follow.
- Safe offline work is complete for this snapshot. Delivery is blocked on that
  approval, not declared complete: Issue 12 stays `needs-info` and has no
  completion commit; Issue 13 remains unstarted. No merge, push, development
  model change or release enablement was performed.

### 2026-08-31 — User-selected local Luna/high connectivity

- Superseding the older Provider proposal above, the user selected
  `CLI_API_KEY`, `http://localhost:8317/v1`, and `gpt-5.6-luna` / `high`. Only
  this worktree's Development configuration and setup instructions changed.
  The existing OpenAI SDK natively accepts `OPENAI_BASE_URL`; no custom
  Provider adapter, credential file, model fallback or compatibility path was
  added. Isolated deterministic tests retain their Scripted Provider.
- The local model catalog returned HTTP 200 and the exact selected model ID.
  An initial host probe failed in its own request-metadata handling after
  sending a request: the SDK already returns an object, not JSON text. The
  parser mistake was reproduced offline and corrected; that attempt's usage
  is unknown and is not counted as a successful Provider verification.
- A fresh Agent image in isolated project
  `thesistrace-test-provider-mtgssx13` successfully streamed through the actual
  Development configuration. The request used `gpt-5.6-luna` with `high`, a
  1,024-output-token ceiling and a 60-second timeout; the observed model was
  exactly `gpt-5.6-luna`, finish reason `stop`, duration 3,156 ms, with 315
  reported input tokens and seven output tokens. This is one connectivity
  result, not total-attempt usage, price evidence, a research trajectory or
  model qualification. No Core, database or Worker service was started.
- Scoped cleanup returned zero and an independent read-only check found no
  containers, networks or volumes for that exact temporary project. The Agent
  image remains available. No existing Development resource was removed.
- Ruff and 110 architecture/lifecycle/production-runtime tests passed, as did
  `git diff --check`. The new contract test failed before the configuration
  change and passed afterward. These current-turn changes are unstaged and
  are not covered by the earlier staged-snapshot reviews. Issue 12 remains
  incomplete; no bulk Eval, delivery commit, merge, push or Issue 13 work ran.

### 2026-08-31 — Align the offline Eval entrypoint with the selected Provider

- Removed the superseded mini/medium candidate and command example. The fixed
  candidate is now `gpt-5.6-luna` / `high`; no old-model alias or automatic
  substitution remains. The explicit Eval wrapper reads `CLI_API_KEY`, maps
  it to the Agent's canonical environment field, and requires the configured
  container endpoint. A generic ambient endpoint or canonical key cannot
  silently replace that selection.
- Eval preflight rejects missing, malformed, credential-bearing or unsafe
  plain-HTTP endpoints. Before any model request it compares the deployed
  Agent endpoint hash with the selected endpoint, and retains only that hash
  in the report. Ordinary deterministic commands explicitly use empty paid
  keys, the Scripted registry and an inert `provider.invalid` endpoint even
  when the launching environment contains real Provider settings.
- The candidate's input ceiling and reasoning support were checked against
  the official Luna documentation. Accounting is explicitly labeled
  `published-standard-upper-bound`, conservatively including long context
  and cache writes; neither the report nor the runbook claims to know this
  local proxy's actual billing. Batch authorization, an applicable charge
  basis and an explicit spending ceiling are still required before execution.
- Red/green regressions covered candidate selection, missing endpoint, CLI
  credential mapping and reference-cost labeling. Agent typechecking and all
  410 Agent tests passed; all 11 network-blocked Eval preflight tests passed.
  Ruff and 120 architecture/lifecycle/production-runtime tests passed, plus
  shell syntax and diff checks. The lifecycle tests needed loopback permission;
  all model credentials were fixed canaries and Docker was a CLI test double.
- A separate real `docker compose config` check confirmed that only the Agent
  receives the credential and endpoint, with exact Luna/high selection. It
  created no services and sent zero Provider requests. No additional real
  model call was made this turn. A new identical-snapshot Standards/Spec
  review is required for these changes; all prior qualification restrictions
  remain, Issue 12 is unfinished, and Issue 13 has not started.

### 2026-08-31 — Close Batch-inspection and causal-repair false positives

- Independent review of staged snapshot
  `879b512ccac341c7fce00e9178954cf8f4b09534e1f6b54a5f87b4f61376f82d`
  reported zero Standards findings and two Spec P2s: one child Result read
  could qualify a two-child Batch, and prestarted parallel submissions could
  qualify as a reaction to an admission rejection. Four new tests first failed
  against that implementation, including the related Formula-repair and
  unresolved-admission cases.
- The single private oracle is now `research-eval-memory`; the former
  correction-only entrypoint was removed, not retained as an alias. Native
  pending invocations and model-step boundaries preserve causal decisions.
  Both Formula repair and admission repair require a later-started call;
  accepted replays cannot retroactively qualify an existing Run. Batch
  qualification also requires matching successful Factor Result reads for
  both distinct authoritative child IDs. Only four closed booleans leave the
  owner-scoped Agent Memory boundary, never Tool parameters or results.
- All 414 Agent unit/contract tests, 11 offline CLI preflight tests, Agent and
  Web typechecks, shell syntax and diff checks passed. The first PostgreSQL
  run retained one default-five-second test timeout during concurrent image
  construction; it is not counted as passing. The complete native-Memory
  correction trajectory now has an explicit 15-second integration-test limit,
  without changing any Agent or real-model Eval execution limit. All 55 tests
  passed in fresh project
  `thesistrace-agent-test-20260831t062439z-21267-69f5d965`; the admission case
  completed in 2,514 ms. The failed run's diagnostic evidence is retained.
- All four final-image Eval Memory E2Es passed in
  `thesistrace-test-20260831t062048z-20259-ea84dacb`. The new Batch test first
  observes two independently completed Core artifacts with inspection=false,
  then true only after the Agent reads both child Results; a foreign child or
  foreign Researcher cannot satisfy the oracle. Formula and actual warmup
  admission correction still pass against native Memory and real Core MCP.
  Overall, secret cleanup, Canary scan and resource cleanup statuses are all
  zero, with no Canary findings. Exact-label read-only checks found no
  containers, networks or volumes for either PostgreSQL project or the E2E
  project. Test images and failed-run diagnostic evidence remain available;
  Development resources and data were untouched.
- A new identical-snapshot two-axis review is required for these fixes. No
  real Provider request was made during this work. Bulk Eval remains paused;
  there is still no qualified release model or completion commit, and Issue
  13 remains unstarted.

### 2026-08-31 — Same-snapshot re-review closed; real Eval still paused

- Both independent reviewers checked the complete 39-file staged snapshot
  `d54636dfdf0a18b05548266d1ac8e9dc955cc86ae133e8736a3744d835a221a5`
  against HEAD `fb6f22c8a55075caf3b2bd2a7b9107de662a6bb1` with unchanged
  beginning/end fingerprints, no unstaged changes and no intervening commits.
  Standards reported zero hard violations and zero judgement-only smells.
  Spec reported zero remaining actionable code findings, closed both P2s and
  found no scope expansion. Each independently passed 70 offline tests; Spec
  also passed ten direct positive/negative final-outcome probes.
- The main thread additionally verified the frozen implementation with Node
  24.14.0 / pnpm 11.9.0: all 414 Agent tests passed with a network guard and
  cleared credentials, all 11 CLI preflight tests passed, and Agent/Web
  typechecks passed. The evidence above remains engineering-only. This final
  tracker entry is the only addition after that reviewed snapshot; no
  implementation or test source changed after review.
- The authorization question is still unanswered. Do not execute the fixed
  33-case-attempt / 36-primary-Turn real baseline without explicit approval
  and an applicable spending ceiling. No real model is release-qualified;
  thresholds and execution bounds remain provisional. Issue 12 stays
  `needs-info` with unchecked acceptance criteria and no delivery commit.
  Issue 13, merge/push, and changes to the running Development system remain
  unstarted. The next action is the user's authorization decision, not another
  unchanged engineering verification cycle.

### 2026-08-31 — Real Eval authorized by the user

- The user explicitly approved the pending real evaluation with “OK，没有上限”.
  This supersedes the authorization pause above. The exact Provider remains
  `CLI_API_KEY` / `http://localhost:8317/v1` / `gpt-5.6-luna` / `high`; no
  substitute Provider or model is authorized. Containers reach the same local
  service through `host.docker.internal`.
- Resume the fixed baseline and subsequent reviewed qualification in the
  isolated linked worktree. Retain the evaluator's existing USD 100 per-run
  protective ceiling and bounded case/turn execution; do not turn this approval
  into an open-ended evaluation loop. All generated research is isolated replay
  data. Never print or persist the credential or Provider response bodies.
- Issue 12 is now `ready-for-agent`, still unchecked and uncommitted. Completion
  requires measured quality evidence, independent review and its own commit;
  Issue 13 remains unstarted until that acceptance unit is complete.

### 2026-08-31 — First real baseline exposed a stateless continuation defect

- Isolated run `thesistrace-test-20260831t065729z-29367-1b407032` reached the
  real Provider and completed two MCP reads in its first model step. The second
  step failed with `PROVIDER_UNAVAILABLE`; its incomplete usage correctly halted
  the baseline after one of 33 case attempts. This failed report remains under
  that run's evidence directory and is not research-quality qualification.
- Read-only, content-free inspection of the local proxy's matching failure
  established HTTP 404 for an unresolved stored item: the original SDK request
  relied on an `item_reference`, while the proxy forwarded `store: false`.
  A separate bounded two-step synthetic probe without reasoning references
  passed, so connectivity alone could not detect this defect. No private proxy
  request or response body was exported. A proposed full-log replay was rejected
  by the safety boundary and was not executed; its throwaway launcher was removed.
- The existing public model-adapter contract now has a deterministic regression
  using synthetic reasoning/Tool history and a stateless external-service stub.
  It failed with the same missing-item refusal before the fix. Selecting the
  SDK's native `store: false` replays encrypted reasoning rather than stored IDs;
  all three model-runtime tests and Agent typechecking then passed. No custom
  provider conversion, automatic retry, fallback or model substitution was added.
- Initializers, data setup and all application health checks passed. The failed
  Eval retained status 1; secret cleanup, raw Canary scan, evidence sanitization
  and resource cleanup all recorded status 0. Independent exact-project checks
  found zero containers, networks and volumes. The removed resources were only
  this run's temporary replay environment; existing Development data was untouched.
- Next: verify the corrected adapter, run a fresh fixed baseline, review measured
  thresholds and execution bounds, then independently qualify the same candidate.
  The failed baseline's total usage remains unknown rather than being recorded
  as zero. Issue 12 remains unfinished and Issue 13 remains unstarted.

### 2026-08-31 — Real trajectory exposed missing model-visible A2UI fields

- Fresh baseline `thesistrace-test-20260831t071408z-34842-5731f9a8` verified
  multi-step stateless continuation. Its first Idea-to-Alpha produced the right
  Core artifact and explanation with complete usage, but took 220,628 ms and
  recorded seven Tool errors. In-place native Memory inspection exported only
  Tool-name/state facts and identified repeated `render_a2ui` output errors.
  The next clarification case also had five Tool errors and failed its artifact
  check; that semantic failure is not claimed to be caused by A2UI.
- Stop this baseline to fix the reproducible input-contract defect rather than
  relax its time/error thresholds. The saved report contains two of 33 case
  attempts (three primary Turns); one additional accepted Turn was interrupted
  and is outside that partial report's accounting. Total-attempt usage therefore
  remains unknown. Exit status 143 and the partial reports are retained. Secret
  cleanup, both Canary scans, sanitization and resource cleanup recorded zero;
  independent exact-label checks found no remaining containers, networks or
  volumes. No Development resource was removed.
- The model saw only an array of arbitrary records, while runtime validation
  expected the registered flat component fields. A new public Tool-schema
  regression first failed on that missing contract. The Tool now derives its
  input union directly from the existing catalog through Mastra's native
  `toStandardSchema` adapter, with no added package or experimental conversion.
  Invalid components/bindings fail at input validation; the independent graph
  projector still rejects invalid references. All 417 Agent tests and Agent/Web
  typechecks pass. All 55 real PostgreSQL tests passed in
  `thesistrace-agent-test-20260831t073944z-45459-4a216b52`.
- One bounded synthetic Luna/high probe generated a valid surface on its first
  Tool call. Its following model step failed the stream guard, so the overall
  diagnostic remains failed, not qualification. It reported complete usage of
  4,768 input and 437 output tokens; no Core data or saved proxy body was sent.
- Independently correct ambiguity in the two momentum prompts: they now
  explicitly request cumulative percentage change in closing price over two
  sessions, not absolute price differences or mean daily changes. The corpus
  snapshot is `research-chat-2026-08-31-explicit-return`; the mathematical oracle,
  fixed repetition count, outcomes and qualification thresholds are unchanged.
  New negative controls retain those distinct signal semantics. This is not an
  assertion about the uninspected cause of the earlier clarification failure.
- Complete final-image regression checks, then run a fresh full baseline against
  this fixed corpus before pinning and independently qualifying release bounds.

### 2026-08-31 — Negative control strengthened the Formula measurement fixture

- The new mean-daily-return negative control exposed a false positive in the
  three original deterministic price panels. Add a fourth fixed panel with a
  volatile round trip whose arithmetic mean return outranks a steadily rising
  instrument while its compounded return does not. This strengthens the
  measurement fixture; the required signal semantics and release thresholds
  are unchanged. All 22 Formula-oracle tests now pass, including the original
  equivalent expressions and both new negative controls.
- Independent exact-project checks also confirmed that the successful
  PostgreSQL run `thesistrace-agent-test-20260831t073944z-45459-4a216b52` left
  no containers, networks or volumes. The final-image regression remains in
  progress; no replacement real baseline or qualification has begun yet.

### 2026-08-31 — Bounded final-image waiting follows observed completion

- Image run `thesistrace-test-20260831t074309z-46238-827c55b7` passed nine
  of ten selected E2Es. Non-empty A2UI data rejection exceeded Playwright's
  default five-second assertion wait. The retained content-free telemetry
  proves Run `76580038-99ce-4394-ad99-892016225b7e` completed successfully
  after two steps in 7,076 ms; the screenshot captured its prior responding
  state. This was not a stuck or failed Agent Run.
- Set the three unsafe-surface scenarios' asynchronous completion waits to
  30 seconds, matching their admission/validation/persistence boundary rather
  than a synchronous UI assertion. No product execution limit, Eval threshold,
  retry count or success assertion changes. Re-run the full selected image
  group after this test correction; the failed run remains failed evidence.
- The original failure diagnostics triggered five `existing_private_value`
  Canary findings, all categorized as diagnostic files rather than service
  logs. Sanitization and the subsequent Canary scan passed. Runtime secret
  cleanup and resource cleanup also passed, and independent exact-label checks
  found no remaining project containers, networks or volumes.

### 2026-08-31 — HTML reporter source-snippet Canary leak reproduced offline

- Run `thesistrace-test-20260831t075426z-50612-0d899c3a` passed all ten
  functional E2Es, but the complete gate correctly remained failed: its raw
  scanner found `existing_private_value` in `playwright-report/index.html`.
  No service-log file was reported. Sanitization, the post-sanitization scan,
  secret cleanup and resource cleanup passed. Independent exact-project
  checks found no remaining containers, networks or volumes.
- A one-test offline Playwright reproduction isolated the cause. A passing
  browser step causes the HTML reporter to retain a nearby source snippet;
  that snippet copied the unsafe A2UI marker literal. Plain non-browser
  assertions did not reproduce it, and changing only the assertion to a
  boolean did not fix it. The marker was located at the closed JSON path
  `tests[0].results[0].steps[1].snippet`, without exporting its surrounding
  contents. Moving the literal into a fixture made the unchanged raw scanner
  pass. This is not a production Agent-log leak or a scanner exemption.
- The browser test now reads that marker from the existing shared privacy
  fixture, passes it into its MutationObserver, and asserts only a boolean
  about page content. All prior negative-surface, replay and continuation
  assertions remain. The full selected image group must pass including its
  original evidence scan; a sanitized failed report never counts as passing.
- Both independent review attempts of the preceding 43-file frozen snapshot
  failed before execution because their selected model was at capacity. They
  produced no review findings or approval. Re-review the updated full snapshot
  after these corrections; Issue 12 and real qualification remain unfinished.

### 2026-08-31 — Image gate and two-axis review passed; native first-step measurement corrected

- Final-image run `thesistrace-test-20260831t081446z-67570-9cb34851` passed
  all ten selected E2Es and the original evidence scan with no findings. Secret
  cleanup, raw scan, resource cleanup and overall status were all zero.
  Independent exact-label checks found no containers, networks or volumes.
- Both independent axes reviewed all 44 staged files at identical start/end
  SHA256 `9775977960fe71c191018c29521c07dfd99a6ff252c9d5d4c814652b7d659ec2`
  against HEAD `fb6f22c8a55075caf3b2bd2a7b9107de662a6bb1`, without unstaged
  changes or commits. Standards reported zero hard violations and zero
  actionable heuristics; Spec reported zero actionable code findings and the
  still-pending real-model qualification. Standards independently passed eight
  offline tests; Spec independently passed 54. Neither invoked a Provider or
  Docker, edited files, or substituted engineering evidence for model quality.
- New baseline `thesistrace-test-20260831t082226z-72416-7a788dd1` passed
  Idea-to-Alpha (79,286 ms), one clarification (101,148 ms), and real warmup
  correction (110,024 ms). Its Formula repair completed but failed the artifact
  measurement. In-place, owner-scoped native Memory inspection exported only
  step/name/state facts and booleans: the original invalid diagnosis preceded
  the first marker; the matching valid diagnosis followed that marker; the
  accepted submission followed the next marker, with all required settings.
- The evaluator incorrectly mapped both the implicit first step and the first
  explicit marker to step zero. A synthetic native-Memory regression reproduced
  this false negative before the fix. The oracle now advances from the initial
  unmarked Tool step at the first marker. Same-step calls, prestarted parallel
  corrections and unchanged admission revisions still do not qualify. This is
  a measurement fix, not a relaxed success threshold or Agent orchestration.
- Stop the flawed baseline and retain its unmodified four-case/five-primary-Turn
  report as incomplete, nonqualification evidence. Six Agent Turns were accepted
  but only five terminal events were captured; the interrupted unreported Turn
  makes total-attempt usage unknown. Exit status 143 remains recorded. Secret
  cleanup, raw scan, sanitization, final scan and resource cleanup all passed;
  independent exact-label checks found no remaining containers, networks or
  volumes. No Development resource was touched.
- The corrected measurement passes all 418 Agent tests and Agent typechecking.
  All 55 PostgreSQL integration tests passed in
  `thesistrace-agent-test-20260831t083629z-78926-f1cae4f7`. A new focused image
  check, same-snapshot re-review, complete baseline and independent qualification
  are required. The preceding review does not cover this later measurement fix.

### 2026-08-31 — Native-Memory review closed; quality deadline no longer cuts off accounting

- Focused final-image run `thesistrace-test-20260831t083806z-79775-14612bc9`
  passed all four Eval Memory E2Es. Secret cleanup, raw Canary scan, resource
  cleanup and overall status were zero, with no findings or remaining labelled
  resources. All eleven offline CLI preflight tests also passed.
- Independent Standards and Spec reviews of all 44 staged files at identical
  start/end SHA256 `847ca164e8990265987e91044b7c76152c046daab856bf87888a856f721a8050`
  reported no actionable code findings. Standards passed ten Memory tests;
  Spec passed 25 focused tests and 41 independent native-step probes. Both
  retained real qualification as unfinished and made no source, Provider or
  infrastructure changes.
- Baseline `thesistrace-test-20260831t084717z-85493-c8be4039` passed its first
  five cases: Idea-to-Alpha (81,837 ms), clarification (98,591 ms), Formula repair
  (102,869 ms), actual admission repair (115,918 ms), and Strategy (158,820 ms).
  Batch then hit the 180-second client deadline, lost terminal accounting, and
  stopped the fixed run after six recorded cases. The retained report correctly
  has unknown total usage, incomplete status and no qualification. Exit status
  was one. Secret cleanup, both scans, sanitization and resource cleanup passed;
  independent exact-label checks found zero containers, networks and volumes.
- A fake-clock regression at the evaluator's actual AG-UI request boundary
  reproduced the defect: a stream returning at 240 seconds failed at the
  180-second quality deadline. Separate latency scoring from observation:
  every submitted Turn now has a finite 630-second transport deadline, covering
  the unchanged 600-second Host Run ceiling plus 30 seconds for terminal delivery.
  The fixed 180-second case quality threshold, candidate thresholds, corpus,
  spending guards and all Agent execution limits remain unchanged. Late cases
  still fail quality; stalled observations still halt with unknown usage.
  There is no reconnect, paid retry or model substitution. A full fresh baseline,
  renewed two-axis review and independent qualification remain required.
- Post-fix verification passed: 421 Agent unit/contract tests, Agent typecheck,
  eleven rebuilt offline CLI preflights and `git diff --check`. The new tests
  cover late terminal delivery, a permanently stalled observation and retained
  accounting with failed latency qualification. Database, production runtime
  and browser code are unchanged by this observation-only correction.

### 2026-08-31 — Observation-boundary review passed; OrbStack became unresponsive during baseline

- Both independent axes reviewed all 44 staged files at identical start/end
  SHA256 `8a19e27faff39ffc1f0766a51b963e07e854217b7b8f5bab49868afb0607ad02`.
  Standards found zero hard violations and zero actionable Fowler smells;
  Spec found zero actionable code defects or scope expansion. Each independently
  passed 36 offline tests. Spec also exercised the actual CLI control flow and
  native AG-UI helper with three synthetic I/O probes and 40 assertions,
  verifying late accounting, finite stalled-stream termination, fixed-denominator
  quality failure, and complete-case budget reservation. No reviewer modified
  code, accessed credentials, invoked a Provider, or operated infrastructure.
- Fresh baseline `thesistrace-test-20260831t090841z-93201-0c52b826` completed
  the first eleven-case repetition with all cases passing, then passed six
  cases in repetition two, including both Batch comparisons. The original
  machine-readable report retains all 17 successful observations; this is
  still only 17/33, not a complete baseline or qualification.
- During the second DailyTrack Start case, Docker status/log queries and the
  isolated Web endpoint stopped responding. Independent read-only checks:
  `docker ps` for this exact project timed out after ten seconds; its Web
  endpoint timed out after five seconds; `orbctl status` still returned Running.
  The active context was OrbStack. Host swap usage was approximately 7.6 GB,
  which is a pressure indicator, not a proven root cause. No restart, unrelated
  process termination or Development change was performed.
- Terminate only the verified evaluator PID and its own hung read-only log
  diagnostic. The wrapper records Provider phase exit 143 and successful
  runtime-secret cleanup. It is now waiting on Docker-dependent evidence
  collection/cleanup: final scans, overall exit and resource cleanup have NOT
  been verified. The in-flight unreported case makes total-attempt usage unknown;
  the preserved partial report's known usage is not the total attempt cost.
- Evaluation session `6417` remains the cleanup-wrapper handle, not a live
  paid evaluation. Restore Docker availability before completing cleanup and
  independently checking this exact project's resources. Restarting OrbStack
  would affect other containers and requires separate user approval. Issue 12
  remains unfinished and uncommitted; Issue 13 has not started. The only change
  after the reviewed snapshot is this evidence note, not runtime or Eval code.

### 2026-08-31 — Docker recovered; interrupted environment safely closed

- On resume, Docker responded again without any restart by this task. The old
  evaluator/cleanup process IDs and tool handle no longer existed, but twelve
  running Test containers remained. Current worktree, branch, HEAD and staged
  SHA256 `02642a37447a5720369315ac99da42e5c932afe317736c00ca6a3dc5e7b4aef2`
  matched the last handoff, with no unstaged changes.
- Reuse the existing runtime evidence functions through a clearly marked
  one-off ignored recovery script. Capture succeeded; the unchanged original
  Canary scanner passed with no findings, followed by successful failure
  sanitization and verification. No raw log content or credential was printed.
  Recovered metadata contains 20 accepted and terminal Turns: 19 completed,
  one `PROVIDER_TIMEOUT`, and one Turn with unknown usage. Its elapsed wall
  time was 14,051,929 ms across the outage. This is not proof of a specific
  outage cause or a successful execution-limit test.
- The canonical `scripts/test-runtime cleanup` command succeeded for this
  exact Test project. Independent label-filtered Docker queries verified zero
  containers, networks and volumes. Temporary test data is removed; original
  partial reports and recovered diagnostics remain. `recovery-audit.json`
  explicitly distinguishes recovered cleanup from the original incomplete
  wrapper. The original 17/33 report and unknown total-attempt usage are not
  rewritten as complete or qualified. No Development resource was modified.
- Continue with a fresh fixed baseline on the unchanged implementation/corpus/
  candidate snapshot. For this local invocation only, `caffeinate -i` keeps
  idle sleep inhibited for the command lifetime; it changes no permanent
  power setting, runtime limit or quality threshold. This does not establish
  that idle sleep caused the previous outage. Real qualification remains pending.

### 2026-08-31 — Fresh Provider failure retained; bounded connectivity checks recovered

- Baseline `thesistrace-test-20260831t134710z-52572-bf41d936` stopped after
  its first case. The one-step Agent Run failed `PROVIDER_UNAVAILABLE` after
  6,872 ms, before any MCP Tool call; the case took 10,700 ms and usage was
  unknown. The preserved report records Provider failure and incomplete
  accounting, not a model-quality failure or qualification. Overall exit was
  one; secret cleanup, original Canary scan, failure sanitization, verification
  and resource cleanup all passed. Independent exact-project checks confirmed
  zero containers, networks and volumes.
- Bounded diagnostics did not change runtime code, thresholds or credentials.
  The user-selected local port was listening. An authenticated, read-only model
  catalog returned HTTP 200 with the exact Luna model; a credential-free,
  read-only temporary container reached the host service and received HTTP 401.
  That container was independently confirmed removed. These separate network,
  credential and model-catalog checks do not prove inference availability.
- One subsequent explicit synthetic-input inference through the same native
  registered Luna/high adapter completed in 4,562 ms, with 314 input tokens,
  five output tokens and zero reported reasoning tokens. Its limits were one
  request, 1,024 output tokens and 60 seconds, without retry, Tool use or research
  content. Only closed status/usage metadata was printed. The earlier fault
  did not reproduce in this probe; its specific cause remains unproven. The
  failed attempt's unknown usage is not replaced by the probe's known usage.
- Continue a fresh full baseline on unchanged runtime/corpus/candidate inputs;
  neither connectivity success nor an isolated probe qualifies the model.

### 2026-08-31 — Correct a per-step empty-answer false positive

- Baseline `thesistrace-test-20260831t140944z-70749-b6a79e49` stopped at its
  first case with `PROVIDER_MALFORMED_STREAM` after eight model steps and
  114,341 ms. Required Tools, ownership and the independent Core artifact
  checks passed, but conversation/terminal checks failed and total usage was
  unknown. The report remains failed and incomplete, not qualification.
  Overall exit was one; secret cleanup, original Canary scan, failure
  sanitization, verification and cleanup all passed. Exact-project Docker
  queries independently confirmed zero containers, networks and volumes.
- A synthetic, bounded native Mastra/A2UI probe reproduced a separate concrete
  protocol-guard defect twice: a valid rendered surface followed by an empty
  `stop` was rejected for lacking new text in that model step. The second
  probe inspected only closed SSE metadata and character counts in memory:
  text deltas, text-done and completed-output text were all zero; both streams
  had completed events and SDK usage. There was no omitted final text to replay.
  These probes used no Core data and persisted no request/response bodies.
  This establishes the guard defect, not the cause of every unknown-usage
  failure in the full baseline. Probe totals were 4,770/438 and 4,803/491
  input/output tokens; they are diagnostics, not corpus observations.
- First-red deterministic regression uses the actual Mastra Agent and real
  registered A2UI Tool with a scripted two-step Provider. The Tool succeeds,
  then the empty continuation produces an erroneous stream error. The guard
  now checks answer presence across the current Run while retaining per-step
  finish/shape/limit validation. Entirely empty Runs, empty tool-calls steps,
  truncation, post-finish events, refusal and limits still fail closed. No
  prompts, Tools, protocol adapters, model retries or qualification thresholds
  were added or relaxed.
- Verification passed: 428 Agent unit/contract tests, Agent typecheck/build
  and 56 real PostgreSQL integration tests in isolated project
  `thesistrace-agent-test-20260831t142935z-88250-0703f184`. The integration
  includes successful A2UI-only completion, duplicate replay and replay after
  Host restart. Its exit and cleanup were successful. The existing large-table
  scripted fixture now ends without redundant prose, covering the same shape
  in browser acceptance; final-image browser verification is in progress.
- The unchanged bounded real probe passed after rebuilding: one valid surface,
  no errors, two native steps with complete usage, and an empty final `stop`.
  Duration was 16,735 ms; input/output were 4,710/380 tokens, including 152
  reported reasoning tokens. No raw text was retained. This is regression
  evidence only; a new frozen-snapshot review, full baseline and independent
  qualification are still required. Issue 12 remains unfinished and uncommitted.

### 2026-08-31 — A2UI display semantics in Eval; browser admission diagnosis

- Both review axes examined all 48 staged files at unchanged start/end SHA256
  `2bd75dfd80a2649c9f85e5ea36ca77fcb5003adaa1a3515245a0af5ba1b1944e`.
  Standards returned zero hard violations and zero actionable Fowler smells,
  with 70 independent offline tests. Spec returned one actionable P2: the
  actual CLI required ordinary text and ignored validated A2UI explanations,
  contrary to the accepted A2UI result presentation. The reviewer reproduced
  the false negative through the real registered Tool, projector, native
  stream parser and actual conversation predicate; 41 focused tests passed.
  Neither review approved the still-missing real qualification.
- First-red regression now locks down that exact Tool-to-snapshot-to-Eval seam.
  The observer uses final validated catalog display fields, in layout order,
  together with ordinary text. Current-Turn snapshots replace earlier views
  of the same message; invalid/loading/partial views, prior Chat history,
  component IDs, hrefs and layout metadata cannot supply answer semantics.
  The unchanged conversation predicate is now exported from the Eval module
  and consumed by the CLI, so direct regressions exercise its real behavior.
  Merely rendering a card does not satisfy the required result explanation.
  All private display text stays in memory; closed reports are unchanged.
- All 436 Agent unit/contract tests passed, including eight added A2UI Eval
  regressions and negative controls. Build passed; fresh typecheck and rebuilt
  offline CLI checks are running. No candidate, corpus or threshold changed.
- Final-image browser project
  `thesistrace-test-20260831t143104z-89025-dba7f448` failed before admission:
  the Chat POST returned HTTP 503 after about 2.137 seconds, with no accepted
  Agent Run. The visible page said disconnected; this does not demonstrate
  an A2UI or browser event-processing defect. Metadata shows successful Auth
  verification, but does not prove whether the overall verification deadline,
  another admission exception or an upstream failure caused the 503. Host
  load was approximately 19, a pressure indicator rather than a proven cause.
  Overall exit was one; secret cleanup, raw scan, failure sanitization, final
  scan and cleanup were zero; exact-project container/network/volume checks
  confirmed zero remaining resources. Temporary Test data was removed and
  failed diagnostics were retained; Development was untouched.
- Add only a bounded admission-status diagnostic to that browser test, with a
  whitelist of public error codes and no response bodies. Diagnostic replay
  `thesistrace-test-20260831t144607z-95992-f75b8ff3` is in progress. It is not a
  retry-to-green acceptance and does not raise timeouts or change application
  behavior. Full baseline/qualification remain stopped pending this investigation
  and renewed identical-snapshot review.

### 2026-08-31 — Re-review closed; resume a full baseline on the corrected observer

- Both independent axes reviewed all 48 staged files at identical start/end
  SHA256 `83c8625c36c184917636b28fa6a45d1484fc7d4545ea259014de672a47d340cc`.
  Standards returned zero hard violations and zero actionable smells, with
  49 independent offline tests. Spec closed its P2 and returned zero actionable
  findings, with 28 independent tests plus 32 assertions against the actual
  CLI checks block: 14 negative groups, seven retained gates and report privacy.
  Both explicitly kept the real baseline/qualification requirement open.
- Agent typecheck and build passed. One rebuilt CLI run during concurrent image
  building passed ten preflights and exceeded the unchanged ten-second process
  deadline on the missing-budget case. After the image process ended, the
  serialized offline run passed all eleven in 17.05 seconds. The earlier timeout
  remains failed evidence, not a silently retried pass. Current read-only host
  facts were eight logical CPUs, 16 GiB RAM, approximately 7.3 GiB swap used and
  high load; they indicate pressure but do not prove the prior 503's cause.
- Diagnostic image run `thesistrace-test-20260831t144607z-95992-f75b8ff3`
  passed A2UI-only completion, narrow-table interaction and reload replay;
  browser phase took twelve seconds. Overall, secret cleanup, original Canary
  scan and cleanup were zero; no Canary findings. Exact-project queries confirmed
  zero containers/networks/volumes. The retained screenshot visibly shows the
  narrow read-only table and Run complete. This proves the path works, not that
  the previous pre-admission 503 is resolved or that flaky release evidence may
  be ignored. Both diagnostic attempts remain separate.
- Start a fresh fixed 33-case/36-Turn baseline using the corrected frozen code,
  unchanged corpus/candidate/limits and the previously authorized Luna/high
  local Provider. Run heavyweight verification serially. No model substitution,
  timeout increase, automatic retry or unapproved infrastructure change was
  introduced. Only this evidence note differs from the reviewed code snapshot.
  Issue 12 remains uncommitted and incomplete; Issue 13 is unstarted.

### 2026-09-01 — Corrected baseline stopped on a distinct Provider failure

- Full baseline `thesistrace-test-20260831t145809z-1027-9e1548c1` observed four
  of the fixed 33 cases. Idea-to-Alpha, two-Turn clarification and invalid
  Formula repair passed every check, taking 89,506, 92,847 and 127,079 ms.
  Their combined primary reference-cost upper bound was USD 0.0444993;
  this is neither the whole-attempt cost nor verified proxy billing.
- The fourth case's real warmup rejection was corrected: its independent
  artifact, required Tools, ownership, explanation and admission-correction
  assertions passed. Nevertheless, the Agent Run failed with
  `PROVIDER_UNAVAILABLE` after eight steps and 88,878 ms, with incomplete
  usage. The case took 93,079 ms and failed terminal/accounting/cost checks.
  The evaluator correctly halted paid work; unknown usage remains unknown.
  This is distinct from the previously fixed A2UI empty-stop guard defect.
  No later cases ran and no qualification is inferred from the three passes.
- Overall exit was one. Runtime-secret cleanup, raw Canary scan, failure
  sanitization, final Canary scan and cleanup all returned zero; raw findings
  were empty. Independent exact-project container/network/volume queries found
  zero resources. The canonical cleanup also removes this run's image tags;
  retained evidence does not imply that an executable image still exists.
  Development services and data were untouched.
- A separate bounded synthetic host diagnostic exercised ten native Mastra
  model steps, eight sequential counter Tools and one valid A2UI surface using
  the same Luna/high configuration. All ten HTTP responses were 200 with
  complete usage: 23,447 input and 333 output tokens, including 76 reasoning
  tokens, in 51,799 ms. It did not reproduce the Provider failure and is not
  corpus or qualification evidence. No request/response bodies were retained.
- The container-path version initially exited at Docker startup (125) because
  the original image had been removed by canonical cleanup; it sent no model
  requests. After rebuilding only the unchanged Agent image, the same ten-step
  trajectory passed through `host.docker.internal` with the real 1-CPU/1-GiB
  envelope. All ten responses were HTTP 200; usage was 23,458 input and 312
  output tokens, including 55 reasoning tokens, in 49,685 ms. The temporary
  container and image were removed after independent exact-target checks.
- Read-only inspection of the local CLIProxy error log at
  `2026-08-31T15:10:22.251Z` matched the failed case's artifact, exact model,
  high effort and `store: false`. The proxy returned HTTP 500 with
  `server_error`: its upstream POST ended with EOF, and no usage was present.
  Only these closed facts were retained in `provider-failure-diagnosis.json`;
  no raw Provider request, response, header or credential was copied into
  project evidence. The Agent's Provider failure classification is supported;
  the underlying reason for the upstream EOF remains undetermined.
- Host and container synthetic success do not fix or reproduce that EOF.
  Do not rerun a full baseline, alter thresholds or declare the failure fixed
  based on those probes. Requested explicit authority before any modification
  or restart of the project-external CLIProxy service, which other applications
  may also use. No such operation has been performed. Issue 12 remains
  incomplete and uncommitted; Issue 13 remains unstarted.

### 2026-09-01 — External-service authority still pending

- Read-only continuation verified the same linked worktree and frozen staged
  implementation, eleven delivery commits, and no remaining Eval or diagnostic
  containers. The shared CLIProxy listener is still running; a listener alone
  does not prove that the upstream EOF is resolved. No new evaluation or
  service modification was performed.
- Set this ticket to `needs-info` while awaiting explicit authority to modify
  or restart that project-external shared service, or an Operator-confirmed
  resolution. The user-approved no-additional-spending-ceiling policy remains
  unchanged; this is a service-authority blocker, not a renewed budget request.
  Preserve the complete Issue 12/13 acceptance scope and serial order.

### 2026-09-01 — Authorized service restart; resume the fixed baseline

- The user authorized restarting the shared local Provider service. Its new
  process and listener were independently verified, and a bounded Luna/high
  virtual-Tool trajectory completed all ten model requests with HTTP 200 and
  complete usage. No model, endpoint, configuration or execution limit changed.
  This resolves the service-authority blocker, not the unproven cause of the
  intermittent failure or the outstanding model-quality qualification.
- At the user's request, remove the temporary Provider probes, diagnostic
  notes and downloaded source/cache; retain the original formal Eval reports.
  The auxiliary `provider-failure-diagnosis.json` referenced above was also
  removed. Do not rebuild those diagnostic artifacts as part of resuming work.
- Continue one fresh, complete fixed baseline in a new canonical Test project,
  on the unchanged implementation/corpus/candidate snapshot. Preserve the
  reviewed 33-attempt denominator, Luna/high selection, USD 100 protective
  per-run reference budget, resource limits, accounting and privacy gates.
  Review the complete measured baseline before independent qualification.
  Issue 12 remains unchecked and uncommitted; Issue 13 remains unstarted.

### 2026-09-01 — Baseline stopped at case 16; native Provider failure classification corrected

- Baseline `thesistrace-test-20260831t163938z-53479-1d5fc58e` ran the frozen
  staged snapshot `f0ac0f5e69f203ef1793a9c73bbcb0d17e87217b959a5c3f4f9f9829c4e44574`
  and observed 16 of 33 cases. Fourteen passed every check. The first Batch
  comparison produced both valid Results and passed capability, ownership,
  explanation and accounting checks, but its 226,250 ms duration exceeded the
  unchanged 180,000 ms quality deadline. It remains a latency failure.
- The second Strategy Backtest produced the independently checked Core Result,
  but its Agent Run failed with `INTERNAL_FAILURE` after seven steps and
  88,483 ms. The case took 90,171 ms and lacked final usage; the evaluator
  halted as required. A preceding MCP transient had already been recovered,
  so it does not prove the cause of the later failure. The retained closed
  metadata cannot identify the original exception. Do not retrospectively
  relabel this report as a proven Provider failure or treat it as qualification.
- Overall exit was one; runtime-secret cleanup, raw Canary scan, failure
  sanitization, final Canary scan and cleanup all returned zero. Exact-project
  checks confirmed no remaining containers, networks, volumes or image tags.
  No Development resources were changed. The 15 cases with complete accounting
  total USD 0.23473342 in primary reference cost; the whole attempt's actual
  primary cost remains unknown, and the reference basis is not proxy billing.
- Native SDK synthetic responses and a real loopback HTTP disconnect exposed
  two independent classification gaps. Node's typed `UND_ERR_SOCKET` cause
  became an internal failure. After output began, SDK-validated Responses
  `error` and `response.failed` objects also became internal failures; rate
  and quota errors lost their category. These are reproducible boundary bugs,
  not proof that either caused the interrupted real case.
- Red regressions preceded each correction. The Provider boundary now uses
  native transport codes and validated event metadata for safe classification;
  private wording cannot select a category. It does not retry, change models,
  invent usage or reinterpret unknown internal exceptions. The original
  loopback reproduction now passes against the compiled implementation.
  No temporary CLIProxy scripts, source cache or diagnostic files were created.
- Agent typecheck/build and all 448 deterministic tests passed. Real
  PostgreSQL integration passed all 56 tests in isolated project
  `thesistrace-agent-test-20260831t174011z-66403-86bf7dc8`, with successful
  cleanup. Independent identical-snapshot review remains required for these
  corrections before another full measurement. The model, effort, corpus,
  pricing, execution bounds and provisional thresholds are unchanged.
  No complete baseline or qualification exists; Issue 12 remains incomplete
  and uncommitted, and Issue 13 has not started.

### 2026-09-01 — Native optional error-code contract corrected after independent review

- Standards and Spec independently reviewed all 50 staged files at HEAD
  `fb6f22c8a55075caf3b2bd2a7b9107de662a6bb1`, snapshot
  `dc7bc1954290cd948a3e317aaf2d3c5c3cc903cb3f22e1595432df78290cab12`.
  Both verified unchanged start/end fingerprints. Standards reported zero
  hard violations and zero actionable smells; Spec found one P2: the pinned
  native SDK accepts omitted error codes, but the new classifier accepted only
  a string or null. The real qualification gate remained explicitly open.
- A bounded, wholly synthetic native-SDK reproduction confirmed both an
  `error` event and a `response.failed` event without a code become
  `INTERNAL_FAILURE`; otherwise identical null-code events are already
  `PROVIDER_UNAVAILABLE`. No network request, credential or temporary file is
  needed to reproduce this current contract mismatch.
- Added regressions before the correction: both omitted-code cases failed
  while both null-code controls passed. The one-condition correction now
  accepts the SDK's current optional code field as an unspecified Provider
  failure. Structured rate/quota codes retain their specific category;
  malformed metadata and unknown internal exceptions keep their prior behavior.
  Private wording is still neither classified nor returned. The original
  compiled native-SDK reproduction now passes with unknown usage preserved.
- The full deterministic gate passed before this final one-condition change:
  955 Python, 448 Agent, 11 offline Eval preflight, 163 Auth and 204 Web tests,
  plus Ruff and all typechecks. After the correction, all 452 Agent tests,
  Agent typecheck and build passed. Previous real PostgreSQL and baseline
  projects were independently verified to have zero remaining containers,
  networks and volumes. No Development resources or CLIProxy settings changed.
- Re-review the corrected identical snapshot before another complete baseline.
  The correction does not prove the cause of the older real interruption or
  service stability. Keep its failed report unchanged, preserve the full
  corpus and provisional thresholds, and keep Issue 12 uncommitted and Issue
  13 unstarted until real qualification succeeds.

### 2026-09-01 — Corrected snapshot reviewed; complete baseline interrupted by upstream TLS EOF

- Both independent re-review axes passed snapshot
  `b02b4633b420c9ec63e04eb936baa240e0ee0acf3e634305f2f0458878401dc9`
  with zero remaining actionable findings and unchanged start/end fingerprints.
  Each independently passed 60 focused tests. Spec also passed 36 assertions
  over six compiled native-SDK streams; Standards reconstructed the prior Git
  blobs to confirm only the documented three-file correction had changed.
- Started the complete fixed baseline in new isolated project
  `thesistrace-test-20260831t180626z-86103-95d5b2b2`, using that exact snapshot,
  Luna/high, unchanged corpus and provisional limits. Final-image build,
  infrastructure, initialization, fixture publication, application health and
  Caddy single-origin checks passed. No Development services or data were used.
- The baseline observed 7/33 cases before stopping. The first five passed every
  check. Batch comparison produced and inspected both valid child Results and
  passed conversation, ownership and accounting checks, but reached the
  16-step `AGENT_LIMIT`: Run duration 227,356 ms; case duration 230,263 ms.
  It fails both terminal completion and the original 180,000 ms quality bound.
  Its seven failed Tool observations all coincide with the terminal limit;
  they are not evidence of seven earlier MCP rejections. Keep the failed
  trajectory; do not qualify it by raising limits or by dropping the case.
- DailyTrack Start failed at step four with `PROVIDER_UNAVAILABLE` and unknown
  final usage. Read-only inspection of the existing CLIProxy service error log
  matched this isolated seed Run and Track plus the terminal timestamp. The
  proxy returned HTTP 500 / `server_error`; its upstream Codex POST failed with
  TLS-handshake EOF before an upstream HTTP response, and supplied no usage.
  This confirms a current upstream-connection failure after the earlier
  authorized service restart. It does not determine the lower-level network
  cause or retrospectively relabel the older internal-failure report.
- The evaluator halted paid work as `incomplete-accounting-or-transport` and
  exited one. Six fully accounted cases sum to USD 0.10201074 in primary
  reference cost; whole-attempt cost remains unknown. The separate title
  reserve is USD 3.6884608, not actual billing. The fixed 33-case denominator
  and all failed observations remain in the formal JSON/Markdown reports.
- Runtime-secret cleanup, raw Canary scan, evidence sanitization, final scan
  and cleanup all returned zero. Independent exact-project checks found zero
  containers, networks, volumes and image tags. No CLIProxy probe files or
  downloaded source/cache were recreated; no service configuration was changed.
- Requested explicit authority before changing connection configuration or
  restarting the project-external shared CLIProxy service again. Do not repeat
  paid baselines while this observed TLS failure remains unresolved. This
  evidence-only entry is the sole change after the reviewed/runtime snapshot.
  Issue 12 remains unfinished and uncommitted; Issue 13 remains unstarted.

### 2026-09-01 — Per-call output-bound correction plan

- A minimized native Mastra stream exposed a local envelope mismatch: two
  individually valid 4,500-token outputs were cut off by an 8,192-token
  whole-Run output processor. The documented envelope is 8,192 output tokens
  per model call and 256 KiB generated bytes per Run. This is independent
  evidence, not proof of the cause of the earlier real Batch failure.
- First add a failing regression at the already-confirmed authenticated
  HTTP/AG-UI runtime seam with real isolated PostgreSQL and the test-only
  Scripted Provider. Assert complete streamed and replayed output, successful
  Run termination, and the retained intervening Tool outcome without querying
  private framework state or performing a real Provider request.
- Correct only the proven scope mismatch. Preserve per-call output settings
  and reported-usage/finish checks, total generated bytes, context, step and
  time limits. Do not raise limits, trim history, add a planner, or treat a
  per-chunk limit as a per-call limit. Run existing negative controls, real
  PostgreSQL and final-image verification, then obtain independent review.
- CLIProxy connection changes still require user authority. Do not recreate
  its removed diagnostics or resume paid baselines while the confirmed
  upstream failure remains unresolved. Real qualification and this ticket's
  completion commit remain open; Issue 13 stays unstarted.
- The HTTP regression also exposed a separate replay loss after the output
  processor was removed: distinct text before and after a Tool streams in
  full, but only the final text returns on reconnect. Pin this at the existing
  native Mastra-to-AG-UI projection seam before correcting it. Read ordered
  native text parts rather than the converter's final-text convenience field;
  preserve Tool redaction and the existing storage/protocol contracts.

### 2026-09-01 — Output-scope and complete-text replay regressions corrected

- The new HTTP/AG-UI regression failed with 27,000 streamed bytes instead of
  the expected 54,000. The other 56 real-PostgreSQL tests passed. Removing
  the whole-Run TokenLimiter restored full streaming without changing any
  configured limit, Provider, model, prompt, or orchestration decision.
- The same regression then exposed incomplete replay. Distinct 4,500-token
  texts before and after the Tool still replayed only one 27,000-byte part,
  ruling out identical fixture content as the cause. A minimized native
  conversion regression failed in 6 ms: the convenience `content` field
  contained only the last step, while ordered native text parts held both.
  The existing safe browser projection now concatenates those text parts,
  preserving Tool payload redaction and excluding other part types. No
  storage change, compatibility branch, framework upgrade or migration was
  introduced.
- Both corrected boundaries pass all 60 focused tests. All 57 real-PostgreSQL
  integration tests passed in project
  `thesistrace-agent-test-20260831t185856z-96505-e05a70ed`, including complete
  54,000-byte streaming, complete reconnect replay, successful terminal state
  and the retained completed Tool. The three red diagnostic test projects and
  this green project were independently checked: zero remaining containers,
  networks or volumes. Their failures remain evidence, not flaky retries.
- A final-image browser regression now covers both output segments, the real
  protected MCP read, reload without resubmission, and a subsequent explicit
  message. The full deterministic gate passed: Ruff, 955 Python, 453 Agent,
  11 Eval CLI preflight, 163 Auth and 204 Web tests, all three typechecks and
  Agent build. Final-image execution and the new identical-snapshot reviews
  are pending. Neither local fix
  proves the cause of the earlier real Batch failure or resolves CLIProxy's
  upstream TLS failure; real model qualification remains open.

### 2026-09-01 — Final-image deletion focus regression plan

- Both independent review axes passed the exact staged snapshot
  `9384edf46242a5a27625bec11c00404c062bf97c78bb07cd47d5e497e996ddf5`:
  zero actionable Standards violations/smells and zero Spec findings. Each
  independently passed 60 focused tests and additional native/public-interface
  assertions. Neither review qualifies the incomplete real-model baseline.
- Final-image project `thesistrace-test-20260831t190710z-9966-f7206a06`
  passed 11 of 12 browser cases, including all seven Provider-failure paths,
  initial streaming, the new complete multistep replay and subsequent Turn,
  protected MCP read and large A2UI rendering. The Research-independence case
  reached successful Chat deletion and New Chat, but its focus-restoration
  assertion failed before later Core preservation assertions executed.
- Retain the failing trace and screenshot. Secret cleanup, both Canary scans,
  evidence sanitization and cleanup returned zero; independent exact-project
  checks found no remaining containers, networks or volumes.
- Minimize the failure at the existing Session UI boundary before changing
  production code. Check whether navigation/focus restoration begins while
  the native modal is still open; modal dismissal belongs to the completed
  interaction, not a later unmount cleanup. Preserve failure/cancel behavior
  and desktop/mobile focus targets, then verify the real browser flow in the
  production image and re-review the changed snapshot. No Provider calls or
  new CLIProxy diagnostic files are needed for this local regression.
- The minimized public UI regression failed in 33 ms: the navigation callback
  observed the native modal still open. The dialog now closes synchronously
  after a successful operation and before navigation/focus handoff; successful
  rename, Cancel, Escape and Close use the same dismissal order. Failed
  deletion still keeps its modal open and displays the error without
  navigating. Native close performs its own modality/focus steps, as defined
  by the [HTML dialog contract](https://html.spec.whatwg.org/multipage/interactive-elements.html#dom-dialog-close).
  No delayed retry, new focus manager or fallback was added.
- The success/failure UI regressions and all 206 Web tests pass; Web typecheck
  passes. Two focused final-image cases cover desktop/mobile deletion focus,
  its persistence once New Chat is ready, and the deleted Session URL. The
  same 12-case gate plus these two cases is running in isolated project
  `thesistrace-test-20260831t192451z-14993-c80167bc`; final-image results and
  independent re-reviews remain pending.

### 2026-09-01 — Dialog handoff verified in the final image and re-reviewed

- The corrected final-image run
  `thesistrace-test-20260831t192451z-14993-c80167bc` passed all 14 browser
  cases and exited zero. This includes the previously failing complete
  Research-independence flow: after deleting Chat, its durable Agent data is
  gone while the admitted ResearchRuns, Results and DailyTrack remain intact.
  Both focused desktop/mobile deletion cases preserve navigation focus after
  New Chat becomes ready and reject the deleted Session URL.
- The same run also passed all seven Provider-failure/recovery cases, initial
  streaming/replay, complete multistep output/replay/subsequent message,
  protected MCP read and large narrow-screen A2UI rendering. These are
  deterministic Scripted-Provider engineering checks, not real model quality
  qualification. The production bundle budget also passed.
- Runtime-secret cleanup, raw Canary scan and cleanup all returned zero.
  Independent exact-project queries found zero containers, networks, volumes
  and image tags. No Development resources or shared CLIProxy configuration
  were modified, and no CLIProxy diagnostic files were recreated.
- Independent Standards and Spec re-reviews passed the unchanged code
  snapshot `2ee65d2cdcd68806fc676b9fa68ea300e20786907c60e430bf52b94c69694193`:
  zero hard-rule violations, zero actionable smells and zero actionable Spec
  findings. Standards independently passed 42 focused Web tests; Spec passed
  43. Both verified identical start/end fingerprints and reconstructed the
  prior snapshot to confirm the four-file scope. Main-thread verification
  remains 206 Web tests and Web typecheck, plus the final-image gate above.
- This completion entry changes evidence only. The confirmed upstream
  CLIProxy TLS failure, incomplete real baseline, measured-threshold review
  and separate qualification remain unresolved. Do not restart paid work or
  modify the shared proxy without the required recovery/authority. Issue 12
  remains unfinished and uncommitted; Issue 13 remains unstarted.

### 2026-09-01 — Model context counted internal MCP presentation copies

- The broader final-image Chat gate in
  `thesistrace-test-20260831t193835z-19282-984ebfb8` passed 41 of 42 cases.
  The remaining DailyTrack case completed Strategy creation, Start and Reload,
  then failed on the repeated Start for the same Origin. That Agent Run had
  completed four model steps, not sixteen; its context estimate reached
  67,214 against the unchanged 65,536 limit. No real Provider was involved.
- Isolated diagnostic runs `20260831t195521z-25187-6b3f65dc` and
  `20260831t201049z-28530-abb58082` reproduced that exact failure. Tagged
  numeric field-size probes showed that Mastra's `toModelOutput` is retained
  in `providerOptions.mastra` on both the assistant Tool call and Tool result,
  in addition to the actual model-facing result. The guard serialized and
  counted all three copies even though Provider adapters ignore the Mastra
  metadata namespace. Diagnostic output contained sizes and protocol field
  names only; all temporary instrumentation has been removed from source.
- A regression at the existing native Mastra/model seam reproduced the
  failure in 164 ms: one bounded Tool result with roughly 24,000 tokens was
  charged as a 72,253-token context and stopped before the next model call.
  The corrected estimate omits only message/part-level Mastra provider
  metadata. It does not change outgoing model options, Memory selection,
  Tool input/output, Tool schemas, other Provider options or any limit.
  The full model-facing Tool result remains available to the next model step.
- Negative controls verify that real Tool input/output containing business
  fields named `providerOptions.mastra` still count and reject an oversized
  context before the Provider is called. All 48 guard tests, all 456 Agent
  unit/contract tests and Agent typecheck pass. The corrected final-image
  42-case gate and real PostgreSQL suite are running; independent two-axis
  review and final evidence remain pending. No real-model qualification is
  inferred, Issue 12 stays unfinished and Issue 13 has not started.

### 2026-09-01 — Corrected context accounting verified and re-reviewed

- Final-image run `20260831t201722z-30222-ac11e3cf` completed successfully.
  Its retained Playwright report records 42 expected passes, zero unexpected,
  flaky or skipped cases and zero report errors. The previously failing
  repeated DailyTrack Start passes together with Batch, capacity, concurrency,
  restart, correction, failure, privacy, streaming/replay, A2UI and Chat shell
  flows. These are Scripted-Provider engineering checks, not real-model Eval.
- The same run records successful image builds, infrastructure initialization,
  data preparation, application startup and Caddy checks. Browser execution
  took 461 seconds; runtime-secret cleanup, raw Canary scan, cleanup and the
  overall run all exited zero. Independent exact-project queries after
  completion found zero remaining containers, networks, volumes or image tags.
- Post-correction verification also passed all 456 Agent tests, all 48 focused
  guard tests, Agent typecheck/build and all 11 offline Eval CLI preflights.
  Real PostgreSQL verification passed 57 tests in isolated project
  `thesistrace-agent-test-20260831t201816z-30620-669093a5`; independent cleanup
  checks found zero containers, networks, volumes or image tags. These results
  do not claim that unrelated Python/Auth/Web unit suites were rerun.
- Independent Standards and Spec reviews both verified the unchanged staged
  snapshot `b167963df15e9ab218eabaf3096e1f29e7b05db896d3f71398efd437569b88b5`
  against HEAD `fb6f22c8a55075caf3b2bd2a7b9107de662a6bb1`. Standards found zero
  hard-rule violations and zero actionable smells; Spec found zero actionable
  code findings or scope expansion. Each independently passed all 48 guard
  tests, plus eight public-interface assertions for Standards and 23 native
  SDK assertions for Spec. Both reconstructed the previous reviewed snapshot
  and confirmed the three-file delta, unchanged review fingerprints and no
  reviewer file/index mutations. Temporary diagnostic instrumentation is absent
  from source and build output.
- This entry only closes the engineering evidence recorded as pending above.
  The last real baseline remains incomplete, including its upstream transport
  failure and unknown usage; no fresh Provider request or recovery verification
  was performed. The runbook's unknown-usage stop remains in effect. A fresh
  baseline needs explicit authority to proceed while preserving that failed
  evidence; threshold review and separate qualification still follow. No
  shared CLIProxy configuration, Development resources or Issue 13 files were
  changed. Issue 12 remains unfinished and has no completion commit.

### 2026-09-01 — Authorized baseline exposed the provisional Provider deadline

- The user explicitly authorized a fresh Luna/high baseline while retaining
  the previous failed and unknown-accounting evidence. The local model catalog
  returned HTTP 200 with the exact `gpt-5.6-luna` entry. A new isolated run,
  `20260901t020548z-86998-3acdd2ea`, preserved the fixed 33-attempt denominator
  and stopped after attempt five, as required, rather than retrying or skipping
  the failure. The first four cases passed every check with complete usage.
- Strategy Backtest created its independent Core artifact and completed eight
  model steps plus thirteen Tool activities. The ninth model step then ended
  after 60,047 ms with no finish event or terminal usage. The final report
  records `PROVIDER_MALFORMED_STREAM`, incomplete accounting and one Provider
  failure. Runtime-secret cleanup, both Canary checks, evidence sanitization
  and isolated environment cleanup all exited zero. CLIProxy created no new
  error log for this request and its active configuration declares no 60-second
  streaming timeout; shared proxy configuration was not changed.
- The event timing and installed Mastra contract identify a deterministic race
  at the existing public model boundary: the framework aborts the step at the
  provisional 60-second budget while the Provider stream closes without a
  finish event. The guard currently records malformed before it classifies the
  already-aborted timeout signal, so its first-failure rule masks the actual
  `PROVIDER_TIMEOUT`.
- Use one vertical TDD slice at `GuardedLanguageModel.doStream`: reproduce an
  aborted step signal and a Provider stream that closes without finish, require
  the public safe failure to remain `PROVIDER_TIMEOUT`, then defer recording a
  malformed stream until the abort signal is classified. Preserve ordinary
  un-aborted malformed-stream failures and all limits. Separately update the
  explicitly provisional Provider-call measurement bound from 60 to 120
  seconds before a new baseline; this is a candidate hard bound to review below the
  180-second case-quality threshold, not a retry, fallback, compatibility path
  or qualification claim. Re-run deterministic tests and obtain independent
  review before making another paid request.

### 2026-09-01 — Timeout classification and 120-second bound verified

- The public `GuardedLanguageModel.doStream` regression first failed with
  `PROVIDER_MALFORMED_STREAM` for an already-aborted Mastra step timeout, then
  passed after malformed-stream detection was deferred to the common failure
  classifier. Ordinary un-aborted malformed streams still fail as
  `PROVIDER_MALFORMED_STREAM`. A second red/green regression fixes the explicit
  Provider-call bound at 120 seconds, below the unchanged 180-second Eval case
  threshold and 600-second durable Run threshold. No retry, fallback, context
  trimming, compatibility path or additional model call was introduced.
- Main-thread verification passed all 50 focused guard tests, all 458 Agent
  unit/contract tests, Agent typecheck/build and all 11 offline Eval CLI
  preflights. Real PostgreSQL verification passed 57 tests in isolated project
  `thesistrace-agent-test-20260901t022745z-93934-fc6dadc2`, including durable
  `PROVIDER_TIMEOUT` behavior; independent cleanup checks found zero remaining
  containers, networks, volumes or image tags.
- Independent Standards and Spec reviews examined the same staged code snapshot
  `87e491851afa71aa60ed1fa50af784da137b85b30fef56a069eb28940f8f8c82`
  against HEAD `fb6f22c8a55075caf3b2bd2a7b9107de662a6bb1`. Standards found zero hard-rule
  violations and zero actionable smells; Spec found zero actionable code
  findings. Both reconstructed the previously reviewed snapshot
  `b167963df15e9ab218eabaf3096e1f29e7b05db896d3f71398efd437569b88b5`
  and confirmed that the code change is limited to timeout classification, its
  tests, the bound/runbook update and this evidence record. They also confirmed
  that the incomplete five-of-33 baseline remains honestly unqualified.
- Final-image run `20260901t023129z-95826-933d423a` passed all 42 selected browser
  cases in 625 seconds. Its retained Playwright report records 42 expected,
  zero unexpected, flaky or skipped cases, `ok=true` and zero report errors.
  The gate includes failure/recovery, privacy, capacity, concurrency, restart,
  MCP, A2UI, Chat lifecycle and independent Research/DailyTrack persistence.
  Runtime-secret cleanup, raw Canary scan, isolated cleanup and the overall run
  all exited zero; independent exact-project queries found zero containers,
  networks, volumes or image tags.
- This entry appends review and deterministic-gate evidence only. The reviewed
  code is now eligible for the already authorized new Luna/high baseline, but
  neither its measured thresholds nor real-model quality have been accepted.
  Issue 12 remains unfinished and uncommitted; Issue 13 remains unstarted.

### 2026-09-01 — The 120-second baseline stopped and exposed failure-source precedence

- Authorized baseline `20260901t025010z-7658-8275b876` used the fixed Luna/high
  candidate, corpus, Dataset, three repetitions and USD 100 protective ceiling.
  It stopped as required after attempt 20 with incomplete accounting rather than
  retrying or continuing paid work. The first 19 attempts passed every declared
  outcome, capability, ownership, conversation, terminal, latency, cost and
  usage check. Both observed `strategy-backtest` attempts passed, including the
  case that previously reached the former 60-second boundary.
- Attempt 20, `daily-track-retry` repetition two, had one Agent Run and zero Tool
  calls. Agent events show acceptance at `2026-09-01T03:24:22.892Z` and a failed
  terminal event at `2026-09-01T03:26:23.176Z`: `PROVIDER_TIMEOUT`, one model
  step, 120,297 ms and unreported usage. The machine report remains unmodified
  and incomplete at 20/33. Its `dataset-worker` source is known to be incorrect:
  the outcome oracle saw the fixture's intentionally pre-existing blocked Track
  and gave that state precedence over the explicit Provider terminal failure.
- An initial public `evalFailureSource` regression failed for Provider, MCP,
  Core admission and Agent-limit terminal codes when a failed Worker fixture
  was also present. Spec review then found that ten other explicit codes,
  including capacity, unavailable and interrupted Runs, still lost precedence.
  An exhaustive regression over every public `AGENT_FAILURE_CODES` value failed
  all ten remaining cases before the classifier was completed. Every non-null
  terminal code now wins; `dataset-worker` is used only when no explicit Agent
  terminal failure explains an independently failed artifact. The blocked Track
  and all old evidence remain intact; no report rewriting or success
  reclassification was performed.
- A separate red/green boundary regression showed that the 120-second Provider
  limit was below the fixed 180-second case-quality ceiling. The provisional
  Provider-call limit is now 180 seconds: a single model step that could still
  satisfy the case ceiling is not terminated early, while a later step has
  already failed latency. The 630-second Eval observation window still only
  preserves terminal accounting across a multi-step 600-second Run. No retry,
  fallback, model substitution or quality-threshold relaxation was added.
- Verification passes 70 focused tests, all 462 Agent unit/contract tests,
  Agent typecheck/build and all 11 offline Eval CLI preflights. Real PostgreSQL
  project `thesistrace-agent-test-20260901t035331z-20494-9ab501ec` passed all 57
  integration tests; independent cleanup queries found zero containers,
  networks, volumes or image tags. The failed baseline's secret cleanup, raw
  Canary scan, failure-evidence sanitization, failure Canary scan and resource
  cleanup all exited zero, with the same independent zero-resource result.
- CLIProxy remained live and its latest error-log timestamp, 03:21:29, predates
  the failed Run by almost three minutes; the 03:24–03:26 timeout created no new
  proxy error log. Shared proxy configuration was not read for content, changed
  or restarted. Final-image verification and identical-snapshot two-axis review
  remain pending. Do not issue another paid request from this evidence alone;
  Issue 12 stays unfinished and uncommitted, and Issue 13 stays unstarted.

### 2026-09-01 — The corrected 180-second snapshot passes final-image verification

- Final-image project `thesistrace-test-20260901t035534z-21127-95ff241c`
  rebuilt the production Agent with the corrected failure precedence and
  180-second Provider bound. Its retained Playwright report records 42 expected
  passes, zero unexpected, flaky or skipped cases, `ok=true` and zero report
  errors. Browser execution took 515 seconds.
- The gate covers Batch, capacity, concurrency, restart, DailyTrack, Eval
  Memory, all seven durable Agent failure categories including
  `PROVIDER_TIMEOUT`, privacy, streaming/replay, protected MCP reads, A2UI,
  independent Research persistence, Auth exchange, connected MCP disconnects
  and readiness failures. Image build, infrastructure, initialization, data
  preparation, application and Caddy phases all exited zero.
- Runtime-secret cleanup, raw Canary scan, resource cleanup and the overall run
  exited zero. Independent exact-project queries found zero remaining
  containers, networks, volumes or image tags. The staged code fingerprint
  remained unchanged throughout the gate; only this evidence appendix follows.
  The first Spec review found and drove the exhaustive terminal-precedence fix
  above. A new identical-snapshot Standards and Spec re-review remains required
  before requesting authority for another paid baseline.

### 2026-09-01 — Exhaustive failure precedence re-reviewed

- The first Standards and Spec reviews of staged snapshot
  `88291a8c55031692bfa3f8c8416478f92ba5ce4aa898c6e513315ecb1f177a1c`
  independently found the same P2: ten public Agent terminal codes could still
  lose to a pre-existing failed Worker fixture. The finding was reproduced by
  the exhaustive red test, fixed, and not waived.
- Both independent re-reviews passed corrected staged snapshot
  `08c3884a091ed920f7747c72a6e25d6af446e869d1beacab053473e4fdd30878`
  against HEAD `fb6f22c8a55075caf3b2bd2a7b9107de662a6bb1`. Standards reports zero
  hard-rule violations and zero actionable smells; Spec reports zero actionable
  findings. Each verified 55 staged files, no unstaged or untracked files and no
  new commit, and reconstructed the prior snapshot to confirm the three-file
  fix scope. Neither reviewer accessed Provider, CLIProxy, Docker or the network.
- Independent focused verification passed 37/37 tests and all 21 public terminal
  codes, while a null terminal plus independently failed Worker still maps to
  `dataset-worker`. Main-thread verification passes all 479 Agent tests, Agent
  typecheck/build and 11/11 offline Eval preflights. The prior 57-test real
  PostgreSQL run and 42-case final-image run remain valid because the review fix
  changes only offline Eval source attribution, its tests and this tracker.
- This entry records review evidence only. The failed 20/33 baseline remains
  immutable and incomplete, with unknown usage on its last attempt. A new paid
  baseline requires fresh explicit authority; threshold review and separately
  authorized qualification still follow. Issue 12 remains unfinished and
  uncommitted, and Issue 13 remains unstarted.

### 2026-09-01 — Baseline and qualification repetition counts are separated

- The user authorized a new Luna/high baseline in isolated Test project
  `thesistrace-test-20260901t043129z-34502-3f6ba759`. After nine of the former
  33 attempts, the user challenged the repeated baseline as too time-consuming.
  The run was interrupted at the completed-case boundary instead of spending on
  another attempt. Its sanitized report remains incomplete and unqualified:
  six of nine observed attempts passed, all nine retained complete usage, and
  the published-price primary-call estimate is USD 0.15140634. The three
  observed failures are retained as evidence: `strategy-backtest` reached the
  16-step Agent limit at 189,630 ms, `alpha-comparison-batch` completed after
  its fixed case deadline at 245,805 ms, and `daily-track-retry` ended with an
  `MCP_TRANSIENT` failure at 91,127 ms. No failed attempt was retried.
- The interrupt exited 130 after the canonical cleanup. Independent exact
  project queries found zero remaining containers, networks, volumes or image
  tags. Shared CLIProxy configuration and process state were not changed. The
  retained report contains only closed facts and no generated text, formula or
  Provider body.
- The former single `repetitions: 3` field unnecessarily applied qualification
  variance sampling to exploratory threshold calibration. The candidate
  contract is hard-cut to `baseline_repetitions: 1` and
  `qualification_repetitions: 3`; the obsolete field is rejected rather than
  accepted through a compatibility path. A complete baseline is now the eleven
  distinct workflow cases once each. Only the independently authorized,
  frozen qualification uses 33 attempts to measure per-case two-of-three
  success and repetition variance. Corpus coverage, prompts, thresholds,
  failure attribution, accounting and stop rules are unchanged.
- The contract test first failed with `RESEARCH_EVAL_CONFIG_INVALID` against the
  split candidate shape, then passed after the parser and runner selected the
  repetition count by explicit phase. Focused verification passes all 39 Eval
  contract tests, Agent typecheck and all 11 offline Eval CLI preflights. Full
  deterministic verification, identical-snapshot Standards/Spec review and a
  fresh complete 11-attempt baseline remain required. The interrupted report
  cannot serve as that baseline because two corpus cases were not observed and
  the candidate configuration digest has changed. Issue 12 remains unfinished
  and uncommitted; Issue 13 remains unstarted.

### 2026-09-01 — Split-repetition review findings fixed

- Independent Spec review of staged snapshot
  `64d09f12e83dfacdaee76a447dd5f18b9a4f3e89271bdaacf072f6367d7b9750`
  found that `qualification_repetitions` still accepted values from three to
  ten, so a value of four could silently expand qualification to 44 attempts.
  Both Spec and Standards also found that the current implementation plan,
  authorization boundary and runbook still instructed an Operator to run the
  obsolete 33-attempt baseline. These P2 findings were accepted, not waived.
- A new regression first demonstrated that `qualification_repetitions: 4` was
  accepted, then passed after both phase counts were made literals: baseline is
  exactly one and qualification is exactly three. The current tracker and
  runbook now state baseline as 11 attempts/12 primary Turns and qualification
  as 33 attempts/36 primary Turns. Historical comments and their old evidence
  remain unchanged.
- Verification on the corrected files passes all 481 Agent tests, Agent
  typecheck/build, all 11 offline Eval CLI preflights and 24 targeted lifecycle
  and Formula-oracle architecture tests. The broader pre-fix split snapshot
  also passed 110 architecture tests; the corrected exact snapshot reran every
  architecture test affected by phase selection or the candidate contract.
  No Provider request, Docker environment or shared CLIProxy change occurred.
- A new identical-snapshot Standards and Spec re-review remains required before
  a fresh 11-attempt baseline. Thresholds, corpus content, accounting,
  Provider/unknown-usage stop rules and the separately authorized qualification
  boundary remain unchanged. Issue 12 remains unfinished and uncommitted;
  Issue 13 remains unstarted.

### 2026-09-01 — Split-repetition findings re-reviewed and closed

- Independent Standards and Spec re-reviews passed the identical corrected
  staged snapshot
  `60a81bd8cdb739e8465183fbb618837547065bad02d44ffee53e3926b8ea7c63`
  against HEAD `fb6f22c8a55075caf3b2bd2a7b9107de662a6bb1`.
  Standards reports zero findings and zero actionable Fowler smells; Spec
  reports zero actionable findings. Each independently confirmed 55 staged
  files, no unstaged/untracked files, no new commit and no reviewer mutation.
- Both reviewers verified the two closed P2s: phase repetitions are exact
  literals one and three, obsolete `repetitions` and qualification value four
  are rejected, and current Operator documentation consistently states
  baseline 11 attempts/12 primary Turns versus qualification 33/36. They also
  confirmed that the eleven-case corpus, thresholds, fixed failure denominator,
  unknown-usage stop, no-retry rule and separate qualification authorization
  did not change.
- Independent focused checks passed 39/39 Eval contract tests and 11/11 offline
  CLI preflights. Main-thread verification on the corrected code passes all
  481 Agent tests, Agent typecheck/build, 24/24 affected architecture tests and
  `git diff --cached --check`; the full split snapshot also passed 110/110
  architecture tests. The interrupted real run records runtime-secret cleanup,
  both Canary scans, failure-evidence sanitization and canonical cleanup as
  successful, with independent zero-resource queries.
- This appendix records review evidence only; it follows the reviewed code
  fingerprint above. No further Provider request has been made. A fresh complete
  11-attempt baseline, measured-threshold review and separately authorized
  qualification are still required. Issue 12 remains unfinished and
  uncommitted; Issue 13 remains unstarted.

### 2026-09-01 — Complete 11-attempt baseline and measured latency review

- Authorized baseline `20260901t053120z-70602-6e35c8f1` ran the frozen
  Luna/high snapshot `90790f5179efa0859b2ba8f75dfd0148b155f203b556d3dd45f3a6b99dcc3ccc`
  once across all eleven corpus cases. The report is complete at 11/11 with
  no halted condition, complete usage and proven reasoning mapping. It records
  ten successful cases and one model-quality failure, for 90.91% task success;
  there are zero ownership, invalid-Tool, forbidden-Tool, Provider, MCP, Core,
  Dataset/Worker or Eval-infrastructure failures.
- P50 is 96,330 ms and P95 is 226,255 ms. Tool error rate is 8.57%, retry rate
  is 0.95%, admission correction is 100%, maximum Run steps are 12 and maximum
  Run duration is 212,519 ms. Primary calls consumed 737,554 input and 34,981
  output tokens, including 16,256 reasoning tokens; the published-price primary
  estimate is USD 0.15335816. Every case passed its USD 1 reference-price
  ceiling. These are reference upper bounds, not measured local-service charges.
- `strategy-backtest` is the only failed observation. Its artifact, required
  and forbidden capabilities, ownership, conversation, terminal status, cost
  and usage all passed; only the provisional 180-second score failed at
  226,255 ms. Earlier retained evidence measured the same complex Strategy at
  189,630 ms and Batch at 245,805 ms, while this baseline measured Batch at
  148,992 ms. The repeated successful business outcomes show that 180 seconds
  was not a stable quality boundary for these two multi-artifact workflows.
  The original report remains immutable with that latency failure.
- A red/green contract therefore pins only Strategy and Batch case scoring, and
  the candidate P95 threshold, to 250,000 ms. The other nine cases remain at
  180,000 ms. The 180-second Provider-call, 16-step, 600-second Run,
  630-second observation and 660-second MCP-token limits are unchanged; this
  threshold review adds no retry, fallback or execution extension. All other
  success, Tool, cost, variance and correction thresholds remain unchanged.
- Runtime-secret cleanup, raw Canary scan and canonical cleanup all exited zero;
  the raw scan has zero findings. Independent exact-project queries found zero
  remaining containers, networks, volumes or image tags. The initial sandboxed
  launch failed before Test-project creation or Provider access when `uv` could
  not read its user cache; the approved identical launch then produced this
  single paid baseline, with no case retry.
- The reviewed threshold change creates a new candidate/corpus fingerprint and
  now requires deterministic verification plus an identical-snapshot Standards
  and Spec review. This complete baseline is calibration evidence, not
  qualification. A 33-attempt qualification still requires its separate
  authorization and must use the newly frozen thresholds. Issue 12 remains
  unfinished and uncommitted; Issue 13 remains unstarted.

### 2026-09-01 — Measured latency thresholds independently reviewed

- Independent Standards and Spec reviews passed the identical threshold-pinning
  snapshot `74f69ec32e92767c2454802cde1f85eb1a6fef802db80bd0a6db659c4e8d1bf2`
  against HEAD `fb6f22c8a55075caf3b2bd2a7b9107de662a6bb1`.
  Standards reports zero findings and zero actionable Fowler smells; Spec
  reports zero actionable findings. Each confirmed 55 staged files, no
  unstaged/untracked files, no new commit and no reviewer mutation.
- Both reviews independently confirmed the complete 11/11 baseline, immutable
  original latency failure, and exact scoring distribution: Strategy and Batch
  are 250,000 ms while nine ordinary cases remain 180,000 ms. They found the
  round 250-second boundary supported by retained 189,630–245,805 ms complex
  workflow measurements rather than a hand-picked retry. The independent
  three-repetition qualification still has to prove stability and variance.
- Reviewers verified that Provider 180 seconds, 16 steps, Run 600 seconds,
  observation 630 seconds, MCP token 660 seconds, every non-latency threshold,
  accounting and stop behavior remain unchanged. There is no retry, fallback,
  compatibility or migration path. Independent checks passed 90/90 related
  tests, 40/40 Eval contract tests, 11/11 offline CLI preflights and staged-diff
  validation. Main-thread gates pass 482/482 Agent tests, Agent typecheck/build
  and 24/24 affected architecture tests.
- This appendix follows the reviewed code fingerprint and records evidence only.
  No qualification request has been issued. Issue 12 remains unfinished and
  uncommitted, and Issue 13 remains unstarted pending separate authority for the
  33-attempt/36-primary-Turn qualification.

### 2026-09-01 — Qualification retained but explicitly deferred

- The user clarified that qualification must remain part of the implementation
  and acceptance contract, but the 33-attempt/36-primary-Turn qualification
  must not run now. No qualification code, configuration, threshold, corpus or
  runbook contract is removed or weakened by this decision.
- No real-model request is authorized by this clarification. Issue 12 remains
  `needs-info`, unchecked and uncommitted; strict serial execution keeps Issue
  13 unstarted until qualification is explicitly resumed and Issue 12 passes.

### 2026-09-01 — User waived this ticket's qualification execution

- The user subsequently gave the exact instruction: “豁免 Issue 12 本次
  qualification 验收，完成并提交 12，然后继续 13。” This supersedes only the
  earlier completion block recorded immediately above. It does not delete or
  weaken the qualification implementation, frozen three-repetition contract,
  thresholds, reports, privacy rules, stop rules or Operator authorization
  boundary.
- The complete 11-attempt baseline, deterministic gates, real PostgreSQL and
  final-image evidence, and closed Standards/Spec reviews remain the evidence
  accepted for this ticket. The baseline is still not qualification, and the
  selected model is not claimed to have passed qualification. With every
  current acceptance item truthfully checked under this explicit waiver, Issue
  12 is complete and may be committed alone before Issue 13 starts.

### 2026-09-01 — Oversized-stream test flake fixed before completion

- The first final Agent gate incorrectly ran tests, typecheck and build at the
  same time. Typecheck and build passed, but one 16 MiB oversized AG-UI response
  case exceeded Vitest's generic five-second timeout; 481/482 tests passed. A
  focused run completed in 715 ms, while ten concurrent focused processes
  reproduced the timeout in 10/10 attempts and nine concurrent processes passed
  9/9. The failure was therefore retained and diagnosed rather than accepted as
  a rerun-only flake.
- The old fixture eagerly encoded and queued the entire body in
  `ReadableStream.start()`, and its five-second test timeout was not a product
  performance boundary. The regression now uses a lazily produced potential
  32 MiB stream, proves that the evaluator actively cancels it just after the
  16 MiB limit, and gives only this non-performance boundary test a 15-second
  ceiling. The ten-process pressure loop passes 10/10 with observed individual
  test times of 4.99–5.67 seconds; the focused test passes in 656 ms.
- Final serial gates pass all 482 Agent tests, Agent typecheck and Agent build.
  No debug instrumentation or throwaway file remains, and no Provider request
  was issued. Because the regression test changed after the earlier reviews, a
  fresh identical-snapshot Standards and Spec review is required before commit.

### 2026-09-01 — Final Spec review findings accepted

- Standards found zero violations and zero actionable smells on staged snapshot
  `f5c72adae7833d9330985cf3897a7d683bce25f1afb75ada2cd8d89f4dca01c8`.
  Spec found three P2s: the Runbook still treated qualification as blocking
  Issue 12/13 despite the explicit waiver, `complete` was premature while those
  findings were open, and the oversized oracle observed cancellation without
  pinning the byte boundary. None was waived.
- The Runbook now keeps qualification as the model-release decision while
  honoring the ticket waiver; no baseline is relabeled. This tracker returns to
  `ready-for-agent` until all findings are re-reviewed. The lazy fixture records
  bytes produced with source prefetch disabled and requires cancellation at
  exactly 16 MiB plus the next 64-KiB chunk, so an earlier protocol exit or a
  17–31 MiB limit fails the test. Its first assertion exposed the default
  one-chunk `ReadableStream` prefetch at 16 MiB plus 128 KiB; pinning the test
  source to `highWaterMark: 0` makes the oracle observe consumed bytes rather
  than queued bytes. The corrected focused suite passes 68/68 and Agent
  typecheck passes. A new identical-snapshot two-axis re-review is required
  before setting this ticket to `complete` and committing it.

### 2026-09-01 — Final two-axis re-review closed

- Standards and Spec independently re-reviewed identical staged snapshot
  `bde2f7c043a97a41bb9d9a1aa43053871e2b58559cde93534f859c9f891e85a8`
  against HEAD `fb6f22c8a55075caf3b2bd2a7b9107de662a6bb1`. Both confirmed 55
  staged files, no unstaged/untracked files and no post-HEAD commit. Standards
  found zero hard violations and zero actionable Fowler smells; Spec confirmed
  all three P2s closed with zero remaining findings.
- Each reviewer independently verified the Runbook waiver/release distinction,
  the temporary `ready-for-agent` state, and exact oversized cancellation at
  16 MiB plus 64 KiB with prefetch disabled. Their offline checks passed 28/28
  stream tests and 68/68 focused Eval tests respectively, plus staged-diff
  validation. Main-thread final gates pass 482/482 Agent tests, Agent typecheck,
  Agent build and 11/11 offline Eval CLI preflights; no Provider call ran.
- This final delivery entry and the `complete` status are the only changes after
  the reviewed snapshot. The implementation, tests, Runbook and qualification
  mechanism are unchanged; their staged diff SHA256 excluding this tracker is
  `30396a4a49251f2cccc2ab1f61badefa0aa44c0109c52ed73fd8a73118c7bfb0`.
  Issue 12 is ready for its independent commit, after which Issue 13 may start.
