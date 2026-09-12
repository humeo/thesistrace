# 08 — 每日共同条件仓位实施计划

2026-09-13，基线 `c62c085`，隔离工作树 `codex/research-capabilities`。07 已完成验证、串行 Standards/Spec 审查与独立提交。只开始08，09及以后不提前实现。

## 交付边界

遵循 [票据08](../issues/08-daily-exposure-adjustment.md) 和母规格每日 Exposure 语义。Exposure 使用共享表达式的常量/共同每日数值，不能读取个股或账户；每天 Close 决定、下一 Open 执行。保留单一当前合同，无兼容、迁移、版本升级或有状态 trade_when。

## 已确认实现事实

- 07 的常量 Exposure 使用共享编译/Series evaluator，但准入与 Kernel warm-up 仍只看 Signal。08 必须联合依赖、共同指标、历史窗口与预算，不能只放开编译器。
- `research_kernel/strategy.py` 当前只在 Selection 周期 Open 消费 Pending Target，完整先卖后买；需要新增明确的 selection/reduce/increase 决策模式，不能让中途调整落入完整等权再配置。
- Target Selection、Target Exposure、Pending Target 已贯通 Run/Batch/Track；应扩充现有状态中的决定日期/模式，继续从冻结目标恢复，不重算旧 Close。
- Run/Track 共同指标证据、输入身份及缓存预算目前引用 Signal；Exposure 引入的共同依赖也必须进入相同发布/读取/恢复路径。

## 实施顺序

1. 先补共享编译/标准化表达式的成功与拒绝测试；允许共同每日数值 Exposure，保持股票/账户/布尔根拒绝。联合两表达式真实依赖、有效窗口和工作预算，复用当前 Module。
2. 通过共享执行计划计算每日 Exposure，严格有限0–1；只在研究 Close 形成决定，warm-up 不交易。静态/数据就绪诊断与正式准入同源，非法执行值中止 Advance 且不发布部分状态。
3. 先写手算状态回归：Selection5 下100%→30%→0→恢复、同日合并、相同值无交易、价格漂移、卖出受阻无补偿、不自动重试。实现三个明确模式：完整配置；按实际价值比例只减不买；按保留名单补缺只买不卖并限制总增量预算。
4. 冻结决定日期/模式/Exposure/名单权重，通过完整与紧凑 Run、Batch、Track 原点/Checkpoint/终态及共同输入产物贯通。验证跨段和缓存恢复，旧发布状态不覆盖。
5. 更新共享目录作用域、编辑器/补全/诊断、冻结来源以及目标/实际偏离展示；固定百分比仍编辑同一表达式。HTTP/MCP 与网页只公布已实现行为。
6. 跑定向模块、当前合同、实际隔离 Run/Batch/Track 和相关真实浏览器验收；按失败边界扩大验证。然后串行 Standards → Spec → 修复复审 → tracker → 独立提交，才开始09。

## 验证重点

- Signal close + Exposure 嵌套共同窗口：准入窗口含两者并保持原研究起点；仅 Exposure 的行业依赖也冻结并计算。
- 六万/四万持仓降到三万：目标一万八/一万二。受阻股票不导致另一只超额减仓；实际已经低于目标不反向买。
- 加仓只补保留候选缺口；不卖超配者，总买入金额与费用同时受目标差和现金限制；空仓中更新的新名单用于恢复。
- 双触发一次完整目标；末日正常交易并冻结未来决定；无变化不因漂移/受阻再次下单。
- 真实发布与 Track 原子失败保持前次状态；选取当前隔离入口，不操作 dev/生产。

## 执行记录

- 2026-09-13：计划建立，尚未修改08产品实现。

### 2026-09-13 — Shared daily expression and first account slice

- Shared Exposure compiler and normalized IR now permit Number/common daily Numeric Series, reject stock/account references and Boolean root; constant values still validate statically, common values validate at each completed research Close. Initial tests4failed/8passed; repaired evaluator test fixture to supply field dependency and immutable tuple series. Combined expression regression66passed (`expression-green.log`).
- Added joint expression requirements for data fields, common industry coverage, max lookback, node/work totals and depth. Current private `expression_admission` replaces the misleading Signal-only name in callers/fixtures, without an alias or reader adapter. Source and normalized Exposure remain frozen. A Signal-close/Exposure-industry-window test now diagnoses the Exposure field, requires its historical coverage, and preserves the requested research start. Relevant admission/expression43passed (`admission-green.log`).
- Added account-series evaluation through the existing common aggregation and Series evaluator, avoiding stock broadcast for the account result. Pending Target now records its decision Session and selection/reduce/increase mode; scheduled decisions and changed Exposure execute only at the following Open. Selection uses full allocation; reduction freezes proportional actual-value targets and never buys; increase never sells and caps aggregate buys by the positive target gap in addition to cash/fee checks. Equal unchanged Exposure does not create a new target.
- Independent six/four-to-three account expected42000/28000 sales, leaving18000/12000, passed. Added actual-already-below-target, overweight-name increase budget, and zero-to70% recovery cases; all19manual account tests passed (`direction-budget.log`). Current Run/Chunk regression44passed (`kernel-second.log`). Initial broad failure was a too-strict field-binding equality introduced during separating Signal lookback from joint warmup; retained the existing supplied binding contract while deriving Signal lookback independently. No runtime fallback added.
- Changed private Kernel warmup naming to `effective_lookback` and kept Signal plan lookback independently derived, so joint requirements do not mislabel Signal windows. Current Core source Ruff and changed-test Ruff passed (`ruff-current.log`); whitespace check passed.
- **08 remains incomplete/uncommitted.** Still required: propagate Exposure-only common dependencies through actual Run/Batch/Track data reads and evidence publications/coverage checks; shared Alpha artifact must not acquire per-Strategy Exposure results; add actual daily Exposure continuation/cache/failed-Advance tests, blocked/no-retry and longer100→30→0→restore sequences; update catalog/completion/UI/HTTP/MCP views and current schema fixtures; run necessary real isolated/browser gates, then serial reviews and independent commit. No09 work started, no08 delivery claim.

### 2026-09-13 — Joint data/evidence paths and continuation repair

- Revalidated worktree HEAD `c62c085`; only08 changes outstanding. Extended common reference discovery to multiple expression trees; Run/Batch/Track data reads, result inventories and observation-coverage checks now include Exposure-only references. Batch strategy execution loads its own Exposure fields/history/industry rather than only execution facts.
- Moved shared common-evidence recording into its existing evidence Module. Strategy receives an optional evidence observer; shared Alpha outcomes remain unchanged. Research/Strategy chunk outcomes merge current Signal and Exposure evidence with identity deduplication and mismatch rejection. Full Run and both Advance paths attach only their privately owned result evidence.
- Full Kernel first pass495passed/8failed44.16s (`kernel-all-first.log`): six observation fixtures omitted the new required Pending Target mode/date; two lifetime-test doubles omitted current expression trees. Updated current fixtures (no defaults/adapters). Targeted repaired fixtures plus Run/manual regressions35passed1.45s (`kernel-repair.log`).
- Separated Signal binding identity from joint data requirements: Alpha execution plan/binding uses only actual Signal fields and its own lookback; Kernel accepts the provided union of required dependencies. This keeps a shared Signal artifact independent of each Strategy's Exposure definition.
- New dynamic Exposure cases across row/columnar Advance, Checkpoint projection/restore and historical revisions initially failed5/10 due to merging recalculated warm-up evidence into old dates. Corrected attachment to only new Sessions, preserving historical decisions/evidence. All10passed13.65s (`tracking-daily-exposure-repair.log`), including common-input deduplication and coverage validation.
- New private-artifact tests run baseline and dynamic Exposure from the same shared Alpha output, compare immutable serialized artifact bytes, and check each outcome's evidence independently. Fixed a test-only attempt to JSON-encode an already serialized bytes payload; both2passed0.45s (`private-exposure-evidence-repair.log`). Earlier intermediate account/chunk40passed3.70s (`evidence-first.log`). Source Ruff and touched-test Ruff passed; whitespace repaired.
- **Still incomplete:** UI/context catalog advertises constant Exposure until its actual08 form/contexts/completion are updated; public schemas/inventory/current fixtures need full check; longer dynamic/blocked/no-retry/failed Advance and real isolated Run/Batch/Track/browser acceptance remain. No08 review/commit yet, no09 work started. No test process remains live from this slice.

### 2026-09-13 — Scope-aware editor and current public contract

- Revalidated HEAD `c62c085` and outstanding08 scope; no other ticket started. Read root DESIGN.md before frontend edits. Exposure now uses the same CodeMirror component with an explicit context, shared diagnostics, and the existing catalog result types to omit stock fields/cross-sectional rank in Exposure completion. Signal completion stays available. Percent and expression still edit one persisted source; no second rule or compatibility path.
- Authoring catalog declares daily expressions, Number/common Numeric Series, no stock fields, Close decisions and next-Open execution. MCP local diagnosis description and native test cover a dynamic common expression. Exact current inventory172316bytes, SHA256 `677b84fb2fc53516aa1166688b609ad2d049f723f0de075a40902905d91ad85c`; updated the existing current snapshot/benchmark metadata only, not a new version or benchmark measurement.
- Added Close target versus actual published Open allocation presentation in Run and Track; Track's public observation includes the decided target value. Labels explicitly permit order/cost/rounding deviation rather than promise a hard limit. Corrected affected current TS fixtures for mandatory target and pending mode/date.
- Browser5passed9.3s (`browser-exposure-first.log`): Signal conditional grammar and industry completion; percent/source/diagnosis/reload/submission; unavailable diagnosis recovery; Exposure omits stock completion while Signal retains it, dynamic source survives draft reload. Inspected the actual screenshot `.local/browser-tests/selection-exposure.png`, then made Exposure help text use the existing subdued small-text styling.
- Three affected Web component suites66passed (`web-components-first.log`). Initial added public field caused three TS fixture failures; fixtures updated, `pnpm --dir apps/web typecheck` passed (`web-exposure-view-types-repair.log`). MCP inventory initially had the old07 snapshot; after current snapshot update, native MCP/Track observation52passed2.93s (`public-contract-repair.log`). Source/changed-contract Ruff and whitespace passed. No live handles remain from these checks.
- **08 still not delivered:** necessary actual isolated Run/Batch/Track with dynamic changes, long transition/blocked/no-retry/failed-Advance coverage, final relevant checks, serial Standards/Spec and commit remain. Reuse `.local/test-runs/issue-07/exposure-integration.mjs` isolation pattern for selected actual cases; do not treat current component/module evidence as actual service acceptance. No08 review yet.

### 2026-09-13 — Extended account sequence and real-service diagnosis

- Added independent nine-Session 100→30→0→restore ledger cases, including a new selection while cash and a blocked sell that is not retried on unchanged Exposure. The next scheduled selection creates a fresh target; recovery buys the retained new selection. Added blocked-name proportional-reduction expectations. Manual ledger22passed (`no-retry-sequence.log`).
- Quick first pass stopped at three Ruff findings; repaired. Second pass1385passed/43failed (`quick-second.log`): one architecture test banned all occurrences of `mode`, now narrowed to the public RunInput parameter boundary; remaining failures require loopback sockets denied by the sandbox. Targeted architecture repair29passed/1socket-permission failure. Full quick must run with the already-authorized escalated test environment.
- Current Docker context is OrbStack and its socket /_ping succeeds. Old Docker Desktop socket was stale; no Docker restart or dev stack change. Real-service11-case first pass3passed/8failed (`daily-exposure-integration-first.log`), isolated resources cleaned. Two added fixtures supplied numeric canonical Close values instead of required decimal strings; corrected. Six Batch cases failed while their ordinary Run comparisons succeeded; diagnosis ongoing. A diagnostic assertion edit caused collection SyntaxError in the next attempt; corrected before rerunning. These runs do not constitute acceptance.
- Still no08 review/commit; no09 implementation.

- Follow-up diagnosis: corrected canonical raw/adjusted Close derivation using the existing mapping helper. Dynamic Run→Track then reached final presentation assertions; replaced nonexistent `rebalance` field assertions with published holdings and positive transaction costs for cash/recovery Sessions.
- Batch shared guard still compared all immutable fields except Strategy, rejecting Exposure-specific expression work/budgets. Narrowed it to shared identity while excluding per-Strategy bindings/admission/plan and derived warmup coverage fields; common scope and artifact bindings remain checked. Removed temporary traceback instrumentation. Existing Batch kernel6passed6.40s (`batch-shared-repair.log`). Real11-case repair and escalated full quick are running; not yet acceptance.

- Real-service repaired pass7passed/4failed (`daily-exposure-integration-repair.log`): dynamic ordinary Run→Track and two baseline Sweep cases passed. Remaining Common Batch cases exposed a missed caller in Batch service: `validate_common_chunk_observations` still received the removed single-expression keyword. Updated it to the current complete `expression_trees` contract. No compatibility path. Temporary traceback instrumentation removed.
- Quick third stopped at one undefined diagnostic-assertion variable in a different test; diagnostic assertions now report the completed result directly. Fourth quick and second repaired actual-service run are in progress. Still need explicit failed-Advance atomic preservation and serial reviews before completion.

- Second repaired real-service run **11passed/475deselected121.06s**, full runner exit0 and isolated cleanup complete (`daily-exposure-integration-repair-second.log`). Dynamic Exposure-only universe/industry Run and Track, checkpoint publication retry, baseline/dynamic Strategy Sweep ordinary-result comparisons all passed.
- Escalated fourth quick **exit0** (`quick-fourth.log`): Core1428passed144.58s; Agent648, Auth200 and Web363 tests passed with associated lint/typecheck. Environment-dependent socket failures disappeared under the authorized runner.
- Added real invalid-Exposure Advance case: admitted expression returns1 during Run and2 only on a newly published declining Session; require failed attempt and unchanged published checkpoint, terminal account, observation and strategy. Ruff passed; focused isolated acceptance pending.

- Invalid Exposure actual Advance1passed/486deselected3.27s, runner exit0 and cleanup complete (`invalid-exposure-integration-first.log`). Run succeeds on finite1 values; appended declining Session yields2 and fails without replacing the published account/checkpoint/observation/strategy.
- Added same-day Selection/Exposure case to the independent60k/40k ledger: full allocation intends45k/25k sells rather than42k/28k proportional sells. Initial expected post-sale shares omitted existing round-lot sell sizing; corrected to1300/1900 shares and69200cash. Manual23passed0.25s (`dual-trigger-ledger-repair.log`). Added-test Ruff and diff whitespace passed.
- Beginning serial Standards review, then Spec; no08commit or09work yet.

### 2026-09-13 — Serial review closure

#### Standards

No actionable standards findings.

Reviewed the frozen working-tree changes against baseline `c62c085`, snapshot `AGENTS.md` and `DESIGN.md`, the supplied simplicity/modularity heuristics, and the user's current-contract-only override. Scope included daily Exposure compilation/evaluation, joint admission requirements, Strategy decisions, Batch sharing/evidence, Track continuation/publication, UI/MCP, and changed tests.

The changes reuse the expression engine and formula editor, collect joint admission facts in one small module, and share common-input evidence recording/merging. Exposure-specific Batch evidence remains separate from shared Signal artifacts. Current field/state contracts are updated directly; no introduced legacy alias, runtime fallback, migration, or parallel version path was found. UI changes retain the existing design tokens and explicitly describe decision timing and target/allocation differences.

No heuristic smell was sufficiently material to warrant an actionable finding. This is a Standards review only: it does not replace the subsequent Spec review. Supplied passing verification evidence was considered; no additional tests were run and no repository files were edited.

#### Spec

No findings.

Reviewed the frozen working-tree snapshot against issue 08 and its applicable parent-spec requirements, using baseline `c62c085`. Inspected implementation paths for expression scope and validation, joint admission/dependencies, Close decisions and next-Open execution, proportional reductions, retained-selection increases, combined triggers, continuation/publication, Strategy Sweep sharing and private Exposure evidence, and web/MCP contracts.

The implementation meets the ticket's scoped daily Exposure requirements. No concrete missing requirement, incorrect implemented behavior, or scope expansion was identified. The current-contract-only override was applied; ticket 09 weighting, ticket 11 diagnostic API expansion, and ticket 12 retention behavior were excluded.

This was a read-only Spec review after the completed Standards review. No repository files were edited and no tests were rerun. The supplied quick, isolated Run/Batch/Track, invalid-Advance publication-preservation, manual ledger, and browser verification results were considered supporting evidence rather than independently repeated verification.

- Both reviews closed without findings against the same unchanged70-file snapshot. Required verification is green. Tracker and independent08 commit prepared; no09 implementation begun.
