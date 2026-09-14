# 06 — 补齐 fina_indicator 全部 163 个指标

**What to build:** 在已贯通的供应商财务指标链路上，补齐其余 157 项，让 Researcher 能按用途发现和组合完整 163 项指标；每项有明确单位、固定期间、适用性和实际覆盖，数量增长不改变读取或就绪规则。

**Blocked by:** 05 — 贯通 fina_indicator 的代表性指标链路

**Status:** complete

**Execution contract:** 在从 main 创建并核实的新 worktree 中，严格按 01→08 串行执行。每票开始实现前先记录 Plan；完成实现后逐项验收，进行代码审查、修复及复审，更新 tracker 并形成该票独立 git commit，完成后才开始下一票。审查同样串行，不并行委派实现或审查。

**Latest user decision:** 按用户最新要求，直接实现当前合同，不做兼容、版本迁移或 vXX 升级链；这覆盖母规格中有条件引入迁移的旧提议。保留数据、原有字段语义与必要研究引用的要求继续有效，不将“不迁移”解释为允许清库。

**Execution order:** 06；必须先完成 05 的验收、复审、tracker 更新和独立提交。

- [x] 范围为权威 226 清单中 fina_indicator 的 163 项减去首批 eps、bps、current_ratio、roe、q_roe、netprofit_yoy，即其余 157 项；作者名唯一且不与 Builtin 冲突，日期和更新标记不计入数值入口。
- [x] 复用首批已保存的全部来源列、采集检查点、独立 pending 和版本表，为每个新增字段完善同一个静态 Field Catalog；不因新增作者入口默认重采已完整原始数据，不另建通用可配置注册平台。
- [x] 逐列核实源单位、规范单位、期间、供应商范围、适用性及空值含义，记录可核查来源或对照证据。优先解决 gross_profit 金额尺度、equity_yoy 比例尺度、impai_ttm 实际期间、季度/年度频率和 update_flag 证据能力，不能凭名称推断。
- [x] 已核实的百分数 15 规范为 0.15，原始小数不二次缩放；金额、每股值、天数和倍数各按本身单位。供应商累计、单季、年化、同比或较年初等定义保持独立，不把全部指标当 TTM。
- [x] 复用公告可见时间与观察修订规则；每项按固定期间先选最新可见记录，再取该列，空值不回退到旧非空、别列或三表推算。不伪造来源没有的报表分类或完整历史修订链。
- [x] 有界资格样本覆盖代表性年份、季度/年报和公司类型，记录逐列非空与缺口原因，不能用单个年报推定所有季度。未获证字段不宣布可用；不能删减范围、改单位猜测或换源来完成本票。
- [x] 163 项通过同一 Numeric Series 接口和实际依赖准入。验证少量列与多列读取范围、缓存 Generation 隔离和成本，不预先展开全市场每日财务宽表，不把目录总量当每次读取成本。
- [x] Financial data 聚合供应商家族与当前三表家族，显示实际可用数及部分状态；本票不要求 03、04 已完成，也不能提前声称已具备 204 项财务。中文/DSL 搜索、用途/来源/期间筛选、补全、HTTP/MCP 和 Agent 一致。
- [x] 演示一个跨指标类别公式，从按需查目录、验证、提交到研究结果完整运行。逐列映射和转换由公开接口的独立预期验证，复用首批已证明的采集与版本边界，避免为每列重复整条 E2E。

**Verification:** 母规格 T01、T02、T06、T09、T10、T15。本票只依赖 05；真实全历史采集完整性由 07 汇总，任何资格未决事实须记录为未完成，不能以 163 个名称已注册宣称完成。本票不单独上线。

## Comments

- 2026-09-12：用户确认发布工单。已纳入最新的串行执行、每票 Plan / 验收 / 审查修复复审 / tracker / 独立提交，以及不兼容、不做版本迁移的要求。

## Plan — 2026-09-13

- Predecessor 05 is committed as e8933548 after independent acceptance and serial Standards/Spec review. Continue in the verified codex/field-expansion-226 worktree; no 07 work starts before this ticket is accepted/reviewed/committed.
- Reconcile the authoritative 226-field inventory against the six implemented indicator fields and all 167 retained source columns. Establish one explicit per-field qualification ledger for the remaining 157: authoring name, source column, source/canonical unit, period, scope/applicability, evidence and unresolved facts. Do not register unqualified fields or infer units from names.
- Reuse 05's saved 2023–2025 industrial/bank observations and existing source/statement research. First compute per-field coverage by report period/company type and identify which facts need further evidence. Prioritize gross_margin/gross_profit units, equity_yoy scaling, impai_ttm period, source frequency and update_flag limits. Use official primary documentation and bounded additional read-only source queries only where current evidence is insufficient; no blanket re-download or production Head mutation.
- Implement the remaining qualified definitions in the existing static Field Catalog and current sparse indicator family. Preserve the established first-observation/revision/null semantics, original 12 meanings, six pilot fields and 19 TTM fields. No alternate registry, fallback calculation, compatibility or migration path.
- Verify independent expected mapping/unit/period cases via public catalog/Series APIs, including requested-column projection and current Generation field availability. Reuse existing source and version tests; add only uncovered semantic boundaries. Check 226 unique total fields and 22 Market/204 Financial only once every required indicator is qualified.
- Update the existing Web fixture and verify search/filter/completion and HTTP/MCP/Agent agreement. Run a cross-category indicator formula through the existing isolated research consumers; measure few-/many-column reads and dependency-based costs without dense persisted daily financial data.
- Run affected checks, then serial Standards and Spec reviews; fix and re-review findings, record exact evidence for all nine acceptance criteria, update tracker and create a standalone commit. Source qualification gaps remain explicit unfinished work; do not narrow the 163-field requirement to reach a green count.

## Initial qualification evidence — 2026-09-13

- Verified predecessor commit e8933548 and current worktree. Added reproducible retained-sample inspection and indicator-catalog-coverage.json: all 163 source columns present; 158 have at least one nonnull value across the existing 2023–2025 industrial/bank sample. Five are entirely null: impai_ttm, tangibleasset_to_netdebt, ocf_to_netdebt, ebit_to_interest, q_impair_to_gr_ttm. This is coverage evidence only, not unit/period qualification.
- Rechecked official indicator documentation (https://tushare.pro/document/2?doc_id=79). impai_ttm is described as impairment loss divided by total revenue without a stated TTM period; equity_yoy description does not state its numeric scaling. These remain explicit qualification questions.
- Extended the existing bounded qualification runner with an explicit --catalog request set, reusing credential/request/error/evidence handling. Six read-only requests for 600019.SH and 000002.SZ, 2015–2018: indicator, selected income operands and selected balance operands. Separate output preserves pilot evidence. Purpose: nonnull historical impairment/interest/debt cases and independent amount/growth comparisons; no source-name guesswork or production mutation. Running handle60413; results pending validation.

- Additional qualification handle60413 completed exit0: all six requests returned; each indicator response32 rows, income18 and balance24. No indicator response reached100-row cap. The five previously all-null fields have32 nonnull rows for each added security. These observations improve sampled coverage, not full-history completeness.
- Initial independent check (unique same-period values only): impai_ttm matches cumulative impairment_loss / total_revenue ×100 within four-decimal source rounding for both added securities at20170630,20171231,20180630. Example 000002.SZ20180630 source0.5305 versus computed0.530505801179346. Next compare explicit TTM and quarter alternatives and persist full operand evidence before qualifying its period; do not infer TTM from the name.

- Persisted independent semantic crosschecks and qualification report. gross_margin:30 matches to cumulative revenue-cost in CNY. impai_ttm:30 YTD-percent matches versus18 TTM differences; q_impair_to_gr_ttm:30 quarter-percent matches. equity_yoy:23 parent-equity YoY-percent matches,1 unresolved source-versus-statement discrepancy (600019.SH20171231); unit evidence is distinct from a universal denominator/revision formula claim. Original source retained.
- Coverage inspection now includes all four securities and95 raw indicator rows; all163 source columns observed nonnull somewhere. No full-history or universal applicability claim. Source qualification and catalog implementation remain incomplete; production field count unchanged.

- Added --catalog-operands profile to shared source runner. Six selected three-statement requests completed as47466 exit0; all returned, income18/balance24/cashflow17 rows per security. Existing indicator observations reused. No production Head mutation.
- Added reproducible explicit ratio-scale crosschecks, including single-quarter differences and mean-balance alternatives. Verified several similarly named cumulative and quarterly cashflow fields have different source scales. Corrected candidate hypotheses for profit_to_op (total revenue denominator) and dp_assets_to_eqt (annual mean assets/parent equity), each30 matching samples. Retained failed alternatives and administrative-expense classification discrepancies as evidence; these scripts do not implement runtime fallback formulas. Full per-field qualification/catalog work continues.

- Added explicit 163-field qualification evidence index (indicator-field-qualification-ledger.json) with source/author mapping, coverage pointers, sampled hypotheses, pilot status and outstanding review items. This is an offline evidence ledger, not a second runtime registry or a declaration of qualification.
- Extended scale checks with13 per-share hypotheses: each has18–30 matching samples; operating/net cashflow per-share comparisons explicitly allow half-cent source rounding, other comparisons retain0.0001 tolerance. No missing operands are filled or ambiguous rows selected.
- Added25 growth hypotheses distinguishing prior-year same quarter, prior quarter, and year-start base. Evidence now covers97 fields with scale hypotheses, not97 qualification passes. Quarterly revenue QoQ has28 matching samples per field; source-level growth discrepancies remain recorded. dt_netprofit_yoy and roe_yoy naive reconstructions currently have no matches and require examination of rounding and exact supplier denominator/ROE scope. Do not reinterpret them from the current hypothesis or claim it is the source definition.

- Added separate retained alternatives for diluted ROE YoY (end-equity denominator:22 percent-scale matches/2 differences) and two-decimal deductible-profit YoY rounding (16 matches/8 differences). Original failed hypotheses remain visible; no tolerance blanket or runtime substitution.
- Expanded explicit return/turnover checks; evidence index now contains120 fields with sampled scale hypotheses. Confirmed distinct consolidated/parent/EBIT numerators for npta/roa_dp/roa (30 matches each), cumulative versus quarter mean balances, and quick ratio. Remaining denominator and historical-discrepancy work is recorded in qualification.md; hypotheses count is not a qualification-pass count. No further supplier request or production code change this turn.

- Refined turnover numerator alternatives: total_revenue yields30 matches each for ca_turn/fa_turn/assets_turn and22 for total_fa_trun (remaining operands missing/ambiguous). Kept original revenue hypotheses to show why the scope matters.
- Added19 direct amount/day identities; evidence index now covers139 fields with hypotheses. Confirmed current-capital, retained-earnings, pre-finance operating profit and non-operating profit identities; all32 quarter flow differences and operating-cycle sums match. Supplier fixed_assets does not equal balancesheet.fix_assets_total in30 comparable samples; its components need qualification, not a forced alias.
- Added bounded --catalog-stock-operands profile to shared source runner, four additional selected-column requests for existing securities/periods, preserving prior outputs. Purpose: investment/construction asset scope, noninterest liabilities, expense classification. Run28107 pending verification; no indicator re-download or production change.

- Additional stock-operand run28107 completed exit0: all four requests returned (24 balance rows/18 income rows per security). Immutable prior observation files preserved. Next join operand evidence only on exact source metadata, keeping unmatched/revised records explicit, then verify remaining stock/expense definitions.

- Implemented exact metadata join for overlapping operand observations; conflicting cells become uncomparable and are listed in evidence, never selected by order. Current join has0 conflicts; missing components stay missing.
- Fixed-assets component hypotheses produce15 matches without construction materials and14 with them, confirming a broader aggregate than the single balance column in these samples. Net debt and interest-bearing debt amount identities each30 matches. Admin-expense plus separately disclosed R&D resolves both2018Q3 cumulative differences; quarter R&D operands remain missing.
- ROIC mean-invested-capital hypothesis matches22 samples; end-capital alternative differs30. Annualized variant matches18 and differs4. Evidence index now covers147 fields with hypotheses, not147 completed qualifications; outstanding scope/rounding and untested fields remain explicit. No production field registration or ticket completion yet.

- Primary issuer report comparison confirms rd_exp CNY total research investment and roe_waa percentage for retained600519.SH2024 annual observations; saved exact references/components and numeric equality. These are unit/period anchors, not universal formula guarantees.
- Rounded-turnover day hypotheses each32 matches. Tangible-asset net-equity deduction hypothesis22 matches and operating working-capital30. Indexed151 sampled-hypothesis fields plus primary-report evidence; final explicit field definitions and remaining evidence gaps still pending.
- Clarified qualification boundary: require verified source unit/period/applicability, but do not introduce universal exact historical reconstruction as an extra requirement. Keep source-vs-statement discrepancies visible, never invent a fallback or alter source values to fit.

- Resumed from verified worktree commit e8933548 after checking the original checkout publication only. Added nine explicit offline unit/period/scope decisions for gross_margin, impai_ttm, q_impair_to_gr_ttm, equity_yoy, inventory/receivable turnover days, tangible_asset, networking_capital and cash_to_liqdebt_withinterest. Cash/current-interest-debt ratio has30 scale-1 matches; cash_ratio component hypotheses remain unresolved and are not promoted. Ledger regeneration,163 unique mapping checks, nine evidence-reference checks and git diff --check pass. Runtime admission, applicability review, remaining definitions and public contract verification remain unfinished; no06 completion or07 start.

- Implemented the three evidence-qualified priority fields in the existing static catalog: gross_profit explicitly maps to source gross_margin in CNY; impai_ttm is cumulative percent-to-ratio; q_impair_to_gr_ttm is single-quarter percent-to-ratio. Extended the existing helper with explicit source-column selection, without alternate registry or fallback calculation. Public regression first failed with missing gross_profit, then passed; candidate suite first exposed an obsolete six-field cardinality assertion, now checks retained and newly supported identities without duplicates. Final targeted Series/Candidate/Generation validation:15 passed in2.06s; affected Ruff and git diff --check passed. Ticket06 acceptance and full226 catalog remain unfinished; no standalone partial-ticket commit.

- Added11 evidence-qualified per-share and8 cashflow-ratio fields to the same static catalog, bringing the in-progress catalog to91 total/28 indicator fields. Explicit definitions distinguish ending-stock, cumulative and single-quarter periods; cashflow percentage fields divide100 while already-decimal supplier ratios do not. New19 public-reader cases first failed for absent definitions, then passed. Series/Candidate/Generation suite34 passed1.75s. Broader admission/family/language/expression checks first found the stale browser catalog fixture (101 passed/1 failed); synchronized fixture and count expectations, then102 passed0.48s. Affected Ruff passed after fixing one line-length finding. Desktop/mobile Data browser tests completed as95940 exit0:2 passed8.0s, preserving four sections, search/filter/completion. No full226 claim, review or commit yet; remaining135 indicator definitions/qualification and full-ticket acceptance continue.

- Continued serial implementation in the verified worktree:56 profit/debt definitions,24 growth definitions,46 amount/turnover/return definitions and3 issuer-evidenced research/ROE definitions added. Current catalog220 total/157 indicator fields; remaining6 are fcff,fcfe,fcff_ps,fcfe_ps,cash_ratio,ebit_to_interest. Author/source remaps, cumulative versus ending/quarter/annualized/growth periods and individually verified scaling are explicit static definitions; no second registry or fallback computation.
- Representative regression groups first failed for absent fields (8 profit/debt,7 growth,8 amount/return,1 research/ROE), then passed. Final Series/Candidate/Generation58 passed1.66s; current220 catalog admission/family/language/expression102 passed0.50s. Affected Ruff passes. Browser217-field intermediate state2 passed8.4s;220-field browser revalidation has a separate live handle, not yet claimed here. Fixtures track the current implementation; final226 and full ticket acceptance remain requirements.
- Added actual 2024 interim issuer disclosures to primary evidence: research investment418062861.85CNY, weightedROE17.63percent, roe_avg unit/period anchor17.62percent. Exact reference and scope limit persisted; no universal minimum-selection formula claimed. Metadata ledger regenerated; all prior samples/failed hypotheses preserved. Work remains uncommitted pending full06 acceptance and serial reviews;07 not started.
- Current220-field browser revalidation78376 completed exit0: desktop/mobile2 passed9.3s. All four Data sections, partial readiness, source/purpose/period filtering and formula completion remain verified at this intermediate catalog size.

- Qualified cash_ratio's native multiple scale and report-end period from retained liquid-receivable comparisons; preserved supplier component-scope limits. New public regression failed before registration, then final Series/Candidate/Generation59 passed3.78s and Ruff passed. Current221-field admission/language/expression102 passed0.61s. Five fields remain unregistered; no06 completion/commit or07 start.
- Added bounded free-cashflow hypothesis script and persisted actual operands/differences. Initial cashflow/NOPAT/balance-change hypotheses differ in comparable rows; no runtime formulas added. Follow-up final-operands profile30431 completed exit0:6 requests all returned, per security cashflow17/income18/balance24 rows. Only missing selected statement operands were requested, no indicator re-download. Exact metadata merge retained; additional hypotheses remain mismatched and are not qualification passes.
- Added repeatable requested-column resource measurement54145 exit0 for50 securities×100 coordinates and1/16/158 fields. Arrow bytes176250/776250/6456250; Python traced peak95372/690727/6409595 bytes; traced runtime0.129/0.922/7.536s. Exact projected columns and first/last scalar values checked. This is bounded synthetic current-catalog evidence, not full163 or full-history capacity proof. No production Head writes.
- Current221-field Data browser verification87363 completed exit0: desktop/mobile2 passed11.0s. Qualification ledger and diff whitespace checks regenerated/passed; final five source qualifications and full-ticket resource/consumer/review gates remain open.

- Final source qualification resolves all remaining fields: issuer annual/interim interest disclosures anchor ebit_to_interest cumulative multiple; retained cashflow.free_cashflow comparisons anchor FCFF cumulative CNY (31 matches,2 source differences); borrowing/bond/repayment bridge anchors FCFE (13 matches), and both per-share columns retain independent source values. All failed alternatives and scope limits remain in qualification evidence. Current catalog is226 total,163 indicator,22 Market/204 Financial; audit has no missing definitions or mapping mismatches.
- Final quick suite54775 exited0: Python1397, Agent648, evaluation preflight11, Auth200, Web355 and tooling29 tests passed with associated lint/type checks. Earlier94420 failed on a newly added overlong test line; fixed before this successful complete run. Web emitted socket-hang-up diagnostics in unrelated passing chat rendering tests; no failure was hidden.
- Final226 Data desktop/mobile browser99410 exited0:2 passed12.9s. Prior sandbox attempt73219 failed before browser launch on macOS Mach-port permission; reran with required execution access. Resource measurement6516 exited0 for1/16/163 requested columns: Arrow176250/776250/6656250 bytes, traced Python peak94310/690703/6612128 bytes, elapsed0.070/0.599/5.426s. Exact projected columns and scalar values checked; bounded synthetic evidence only.
- Targeted real-consumer acceptance is running as23009, isolated project20260913t000632z-73271-b08d5a29. Its first sandbox attempt terminated before allocation due uv-cache permissions; current run has required access. Await terminal tests and cleanup before claiming acceptance. No06 review or commit yet;07 remains unstarted.

- Targeted consumer run23009 completed exit0:2 passed,499 deselected,29.33s. MCP catalog/submission, singleRun/Batch equivalence and DailyTrack advancement passed using the cross-category formula. run.txt confirms status=0, cleanup_status=0 and diagnostic/secret cleanup status=0; isolated containers,volumes and network removed. Dependency-restart phases explicitly skipped because unchanged; no full integration/release claim. Standards review is now running against /tmp/thesistrace-issue06-review fixed snapshot; Spec review follows serially.

## Standards review and correction — 2026-09-13

- Reviewed working-tree snapshot /tmp/thesistrace-issue06-review at e8933548. One P2: tangible_asset and four ratios were qualified as tangible net-equity but still displayed Chinese asset labels. Updated five labels to 有形净资产 with explicit supplier scope; synchronized public fixture and authoritative226 inventory/CSV/Markdown/ledger. DSL identifiers, source columns, units and periods remain unchanged.
- Standards re-review of /tmp/thesistrace-issue06-review-r2 closed the P2 with no new findings. Public Catalog/Series tests84699 passed112 in0.61s; final desktop/mobile browser73753 passed2 in9.2s. JSON parsing and retained-observation credential-key inspection pass; git diff --check passes. Spec review now proceeds serially against the same r2 snapshot.

## Acceptance evidence map

| Criterion | Current evidence |
| --- | --- |
| 1 — exact163/remaining157 unique author scope | Explicit catalog plus indicator-catalog-audit.json:163 implemented,no remaining/no mismatches; public catalog226 identity contract passes. |
| 2 — reuse retained columns and one catalog | Production diff changes only fields.py static definitions/helper source mapping; source schema167 and sparse ingestion/version ownership inherited from committed05. No additional runtime registry. |
| 3 — source qualification | Per-field qualification ledger, original observations, numeric hypothesis outcomes and issuer annual/interim references. gross_profit/equity_yoy/impai_ttm and supplier update evidence limits documented. |
| 4 — explicit scales and periods | Public Series independent expected examples cover CNY,per-share,day,multiple,percent/native-ratio,quarter,annualized,YOY/year-start distinctions; audit compares all source/units/periods to offline explicit decisions. |
| 5 — latest visible supplier value | Existing05 resolver/version behavior preserved; public Series regressions verify null/conflict hides old values and old-report revision cannot replace newer report. No source reconstruction introduced. |
| 6 — bounded multi-period/company evidence | Five securities,127 indicator observations,163 columns nonnull somewhere,period/company coverage matrix and source scope restrictions retained. No universal company availability or full-history claim. |
| 7 — sparse demand-based reads |1/16/163-column measurement over5000coordinates; exact projection and values verified. Existing Generation rejection and projection/caching contract coverage preserved. |
| 8 — consistent consumer catalog | Final226 fixture equality, desktop/mobile search/filter/completion tests, actual MCP source/unit lookup. Existing03/04 already committed, so current22 Market/204 Financial claim is supported at catalog level. |
| 9 — complete research example | Isolated real MCP submission/Worker and singleRun/Batch/DailyTrack formula equivalence:2passed29.33s; cleanup_status0. Full quick suite passed; source and conversion tests use independent expected literals. |

These are06 implementation and bounded acceptance evidence;07 owns full-history construction and08 owns final integration/cutover. No production publication is claimed.

## Final review and delivery — 2026-09-13

- Serial Spec review of r2 passed with zero actionable findings after Standards P2 correction and clean re-review. All nine criteria above are satisfied. Reviewers examined static snapshots; primary task separately ran the recorded tests.
- Final qualification-ledger status now records completed bounded review/acceptance; applicability points to actual five-security per-field coverage. These final metadata/tracker changes do not alter source values, catalog or reader behavior.
- This tracker update accompanies independent commit `feat(data): complete the financial indicator field catalog`. No push or production cutover;07 and08 remain outstanding.
