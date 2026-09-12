# 10 — 波动率倒数配权执行计划

基准 `9c5e267e`；隔离 worktree `research-capabilities`。09 已完成验收、串行 Standards/Spec 审查并独立提交，确认工作区干净后开始10。仅实现本票，不提前实施11–14；使用单一当前合同，不增加迁移、别名或版本读取。

## 已核对边界

- `research_kernel/portfolio_weighting.py` 负责最终候选排序和配权；09 已使用精确有理数串保存冻结相对权重，交易核心按资本乘分子再除分母计算。
- `research_kernel/strategy.py` 在 Selection Close 调用配权并保存名单/权重；每日 Exposure 与下一 Open 执行已有共享循环，不能为逆波动另写循环。
- `research_run/service.py` 准入和恢复验证当前合并 Signal/Exposure 的 `expression_requirements`；10 必须加入 Weighting Close 字段及收益窗口的前一观察。
- `kernel_run.py` 冻结字段、lookback 和 Calculation Sessions；Track/Batch/网页来源须贯通窗口，不能只添加选项。

## 实施顺序

1. 先以人工调整后 Close 验证总体标准差、完整窗口、零波动/不足/不可用排除顺延及 0.1/0.2 → 2/3、1/3。补失败用例后增加纯配权规则；不吞基础设施错误，不加 epsilon 或等权兜底。
2. 加入当前 inverse-volatility 模型和整数窗口（默认20，1–252）；整份配置准入、真实依赖、联合 warm-up、资源预算与冻结来源一并贯通 Run/Batch/Track。研究起点不移动。
3. 在现有 Selection 边界读取截至当前 Close 的历史收益，先筛选资格再取至多 N 名并归一化。保存排除原因供现有诊断通路读取；全无效形成空目标且不改 Exposure。
4. 网页配权选择及条件窗口输入、草稿复用、整份诊断/提交、HTTP/MCP 目录和来源同步交付；遵循 DESIGN.md。
5. 运行独立权重与公开账户测试、未来扰动/缓存与分段恢复、真实准入/发布/Batch/Track 验证及相关网页和 MCP 检查，再按边界决定快速检查。
6. 固定输入后串行 Standards → Spec；修复并复审，更新 tracker，独立提交后才开始11。

## 验证重点

- 窗口 N 个收益需要 N+1 个 Close；选股当日 Close 可用，之后价格不可影响当日权重。窗口1的总体标准差为零，按规则排除，不隐式改窗口。
- 候选不足只在有效者间分配；全部无效时即使 Exposure=1 也无股票目标；有效候选恢复后沿正常选择规则建仓。
- 零仓位仍保留已决定名单和精确权重；仅新 Selection 更新，缓存恢复不重算旧决定。
- 诊断与提交、普通回测与 Batch、Track 冻结来源使用同一模型/窗口；基础设施失败继续走既有失败/重试边界。

## 执行记录

- 2026-09-13：09 提交 `9c5e267e` 后建立本计划。尚未修改10产品代码或测试。

- 2026-09-13：先补 `test_inverse_volatility_weighting.py`，缺少实现的导入失败已确认；新增纯 `inverse_volatility_selection`，复用 Final Alpha/身份排序。总体收益波动使用34位 Decimal，倒数以 Fraction 精确归一化并保留09当前有理数字符串。无效候选按原因返回，数据访问映射缺项抛出错误，不当成资格失败。14个逆波动用例及13个既有配权用例共27passed0.19s；覆盖手算2/3:1/3、顺延、窗口1、有效不足、无效Close和访问错误。Ruff发现zip显式strict和行宽问题后修复。
- 尚未接入公开枚举、配置窗口、联合依赖、实际账户、资格诊断或网页/MCP；10仍未完成/未提交，不开始11。下一步贯通Window与Weighting requirements，然后在Selection Close调用本规则。

### 2026-09-13 — Current window contract and account integration

- Current `PortfolioWeighting` includes inverse_volatility and `VolatilityWindow` is strict integer1–252. Public Strategy/Batch default20; immutable input, authorable source, Kernel Strategy, Track provenance/checkpoint and every execution caller explicitly carry volatility_window. Current test dictionary fixtures updated; no old-input fallback.
- Joint `expression_requirements` adds adjusted Close, window lookback (N returns require N preceding observations plus decision Close), and workload for inverse weighting. Run admission and frozen-contract validation share it. Kernel requires field and sufficient lookback. Track checkpoint now preserves run_input.effective_lookback instead of Signal-only lookback.
- Existing Strategy Selection calls inverse selector with histories sliced through decision Close; existing Open/account loop reused. Eligibility exclusions append dated instrument/reason/window diagnostics; Exposure unchanged. Row and columnar data access paths use actual adjusted Close. No alternate transaction loop.
- Manual account test sigma .1/.2,100k×.6 at price10 expects4000/2000shares and40000cash. FutureClose10/999 leaves frozen weights unchanged. First2failed due test using wrong position key shares; corrected to public execution_shares. Combined inverse/manual41passed0.23s.
- Kernel full556passed/1expected Strategy checksum failure59.91s (`.local/test-runs/issue-10/kernel-first.log`): explicit volatility_window changes frozen Strategy identity; Alpha/labels/Factor unchanged. Current Strategy checksum70bf52f83a6bfc9a51016ae581ac64795c506ebeb673dc5a95033e8e8fa768fc; remaining characterization2passed0.11s. Source/tests Ruff and diff whitespace pass after formatting repairs.
- New admission verifies volume-only Signal still requires Close and4 warm-up sessions, leaves requested start unchanged, and rejects missing Close. Initial scalar Signal test invalid(ROOT_MUST_BE_SERIES), replaced with volume. All common-input admission12passed0.18s.
- Frontend draft/spec/source carries volatilityWindow string / volatility_window number, default20. Inverse option and conditional1–252 window input plus eligibility help added, source shows frozen window. Current TS fixtures updated; Web typecheck initially missing current fields, repaired exit0 (`web-types-repair.log`). Authoring catalog advertises inverse/window and eligibility semantics.
- **10 incomplete/uncommitted.** Still need direct public enum/window rejection tests, broad HTTP/MCP inventory updates, browser inverse-window flow and actual screenshot, full component checks, real inverse Run/Batch/Track publication/cache/continuation (including zero Exposure restore and all-invalid paths), verify diagnostic persistence/access and legal-history classification, then serial Standards/Spec and independent commit. No11 work. No live test handles:95175/89715/3584/13326 consumed terminal results.


### 2026-09-13 — Browser, tracking and real publication verification

- Browser test now runs rank and inverse variants; inverse default20 changed10 persists reload and matches diagnostics/submission.4passed7.4s (`browser-first.log`), screenshot inspected. Found rank-specific help still visible for inverse; made help conditional for allthree models. Repaired browser4passed19.9s (`browser-help-repair.log`). Latest screenshot `.local/browser-tests/selection-inverse_volatility.png` needs final visual reread after help repair.
- Web components56passed2.73s (`components-first.log`). Subsequently added inverse frozen-source/window render case; needs rerun (27RunFacts instead of26).
- Rank/Equal/Inverse Track parameterization: inverse10passed13.36s (`tracking-first.log`), row/columnar comparison, historicalrevision/cache/checkpoint/chunks, and checkpoint union-lookback20 assertion.
- Public strict-window rejection and inverse normalized enum tests added. MCP initial2snapshotfailures/78pass; current inventory174309bytes SHA25624439691553de726a34fde24c122255b12f31fdc950ea9bd020fcd3f8ec60fa6, updated existing metadata. MCP/pure/public80passed5.14s (`mcp-repair.log`). No new version/benchmark claim.
- Actual isolated acceptance first5ordinary/Trackpassed,6Batchfailed (`integration-first.log`). Root cause `_execute_strategy_item_messages` loaded only Exposure fields, omitted inverse Close. Shared-account reader now merges inverse Close and window with Exposure before `_read_shared_window`, retaining shared Signal artifact ownership. Same isolated run repaired11passed77.33s (`integration-repair.log`), runnerexit0 withcleanupcomplete. Tests exercise real inverse Run/Track (including dynamiczero/restored Exposure) plus inverse/rank mixed Batch versus ordinary resultbytes. Fixtures include two historical Close observations; current window2 frozen through provenance. Dockerorbstack/_pingOK; no dev changes.
- **Open functional gap found by inspection:** per-instrument eligibility diagnostics currently exist only in transient Strategy `diagnostics`. Permanent `research_run/result.py` publishes summary/daily/terminal and drops those; public Agent cannot yet inspect actual exclusions. Must fix before reviews. Candidate small design: retain bounded reason counts with latest TargetSelection and expose via existing Run terminal / Track origin-observation sections plus frontend. Keep full transient per-instrument diagnostics; assess ticket/spec requirement for historical evidence before choosing. TargetSelection already propagates through pending/terminal but frontend currently omits its type/display. No implementation of this idea yet.
- Also still verify legitimate asset-history classification (current short list=>insufficient_history, missing Close=>unavailable_return; adapters supply calendar-length lists), all-invalid Exposure unchanged and restoration publicly, then necessary fullquick and Standards→Spec review/commit. No10review/commit, no11. All processes consumed:20359 terminal0,64455 terminal1,83147/28124/31630/77212/14559 terminal0,9830terminal1. No live handles.

### 2026-09-13 — Durable eligibility and bounded numeric state

- Added required current `TargetSelection.eligibility_exclusions`, a bounded dictionary of positive counts for zero_volatility / insufficient_history / unavailable_return. It describes the latest Selection Close and is retained with its date, list and weights through pending/terminal/checkpoint. No daily-holdings artifact or complete historical diagnostic log was introduced. Per-instrument calculation diagnostics remain in the execution output. Run terminal result already exposes TargetSelection; Track Observation now exposes the same accepted/current target_selection through its existing overview/API.
- Shared `SelectionEligibilityView` renders the frozen date and reason counts in Run and Track; empty counts explicitly mean no weighting exclusions. Current frontend fixtures/types updated. Initial JSX sibling and required fixture type errors repaired; Web typecheckexit0, eligibility/Run/Track components41passed2.00s (`eligibility-components.log`). Source/testsRuff and diffcheckpass.
- Empty inverse test first2failed absentfield (`eligibility-red.log`), then manual/terminal40passed0.23s (`eligibility-first.log`). It verifies counts survive a nonselection day, zero candidate list leaves100k cash, and both0/1 Exposure are unchanged. Current literal target-state fixtures directly carry new field, no fallback.
- Real Run/Batch/Track plus new all-invalid public eligibility test12passed122.09s (`eligibility-integration.log`), runnerexit0 cleanupcomplete. New test proves published Run counts positive and Track observation retains identical target including exclusions and empty holdings with Exposure1.
- Found numeric-size defect by inspection and independent100-stock test: exact inversion of34-digit sigma fractions produced631043 weight-string characters. Red `weight-size-red.log`. Fixed by rounding inverse sigma in same34-digit Decimal context **before** Fraction normalization; common decimal denominators avoid product growth, sum remains exactly1, no volatility epsilon/exclusion rule changed. All49inverse/manualcasespassed0.28s (`weight-size-green.log`), including2/3:1/3 money/lot expectation and100-stockstateunder10000chars.
- First fullquick4failed1487passed157.68s: currentStrategychecksum changed for addedeligibility field, max-text provenance dict fixture missingvolatility_window, and2MCPinventory snapshots. Corrected currentStrategy checksum86f035541f4d4eb6530227d0e5f2b18913ec3fa269f8c934085203666f37ea0a; MCP175321bytes/SHA25674be871d2f42a4d4afb368b943e75193238a611f13aeeede2979e65c957f5964. No alpha/labels/factor evidence changed; single current contract.
- Final repaired quick and numeric representation real acceptance are RUNNING. **Live handles:23403** (`quick-repair.log`), **71275** (`precision-integration.log`). Do not restart on observation timeout; consume these results first. Earlierhandles1290/66058 consumedterminal0/1. All web handles consumed. Screenshot with corrected weighting help re-inspected and good.
- Still10incomplete: finish verification, check any findings, then capture current scope and serial Standards→Spec review, fix/re-review, tracker and independentcommit. No10reviewsstarted, no11work. Legal short-history/helper and unavailable-return exclusion remain distinct; reader gaps cannot establish a listing date (InstrumentProfile has listed_to only), so do not invent missing-history evidence or synthesize prices.

- Repaired quick completedexit0: Core1492passed170.30s,Agent648/Auth200/Web368; lint/types passed (`quick-repair.log`). Actual numeric-fix Run/Batch/Track+eligibility12passed135.36s, runnerexit0 cleanupcomplete (`precision-integration.log`). Subsequently extracted the unchanged population-return calculation into a public pure function and added direct .1 variance expectation to distinguish sample denominator; inverse/manual/allTrackexceptunrelatedcoldrollover82passed43.05s (`population-final.log`). Source/testsRuff anddiffcheckpassed. Allhandlesconsumed(23403/71275/77994), no live work. Freeze final10 for serialStandards→Spec; no product changes during review.

- Standards review `/private/tmp/thesistrace-issue10-review/standards-report.md` found oneP2: invalid inverse window stays hidden yet blocks equal/rank form after switching. Reproduced with2failedbrowsercases (`window-switch-red.log`). Shared validity helper now used by form completeness and switching; leaving inverse normalizes only invalid window to20, validwindowsremain. Added adjacent invalid-window text/aria-invalid. Browser6passed17.3s (`window-switch-green.log`); typecheckexit0 (`window-switch-types.log`). Capturing fixedsnapshot for focusedStandardsre-review. NoSpecyet; alltesthandlesconsumed(83756/10475), no live testhandles.

- Final Standards focused re-review closed soleP2 with no new findings. Serial Spec review found no missing/wrong/out-of-scope requirement. Reports in `/private/tmp/thesistrace-issue10-review-fixed/standards-report.md` and `spec-report.md`; all71 reviewed file hashes unchanged before tracker update. Ticket10 all acceptance boxes complete, independentcommit follows. No11 implementation before commit.
