# 05 — 贯通 fina_indicator 的代表性指标链路

**What to build:** Researcher 能在 Financial data 中使用每股、比率、单季和同比指标；先用 6 个代表性字段验证供应商指标从采集、观察版本、财务刷新到研究计算的完整路径，后续指标直接复用同一能力。

**Blocked by:** 01 — 统一现有字段目录、准入和家族合同

**Status:** complete

**Execution contract:** 在从 main 创建并核实的新 worktree 中，严格按 01→08 串行执行。每票开始实现前先记录 Plan；完成实现后逐项验收，进行代码审查、修复及复审，更新 tracker 并形成该票独立 git commit，完成后才开始下一票。审查同样串行，不并行委派实现或审查。

**Latest user decision:** 按用户最新要求，直接实现当前合同，不做兼容、版本迁移或 vXX 升级链；这覆盖母规格中有条件引入迁移的旧提议。保留数据、原有字段语义与必要研究引用的要求继续有效，不将“不迁移”解释为允许清库。

**Execution order:** 05；必须先完成 04 的验收、复审、tracker 更新和独立提交。

- [x] 首批作者入口固定为 eps、bps、current_ratio、roe、q_roe、netprofit_yoy，归入 equity.financial_indicator。逐列核实单位、期间、归属和适用性；q_roe 是单季来源指标，netprofit_yoy 是归母同比，不将整批改成 TTM。
- [x] 从首批采集开始显式请求普通 fina_indicator 的全部 167 个来源列，保留 163 个数值来源和 4 个元数据列；其余指标暂未通过资格或实现时不声明可用。6 项是正常实施范围，不创建临时功能开关、独立目录或第二版响应。
- [x] 使用历史 Instrument Identity，普通单股接口按有界报告期区间取数，包括所需 pre-start 报告及历史退市证券。start_date/end_date 是报告期过滤，不能充当公告增量游标；达到 100 行上限继续验证完整性，不假定 offset/limit 有效，最小分片仍不确定则未完成。
- [x] 在既有 Operator 流程保存原始响应、报告期、公告日、来源更新标记、首次观察和内容哈希。同内容重试去重并保留最早观察；接口没有保证的 report_type、comp_type 或修订时间不得填造。
- [x] 有公告日期的记录从下一 Research Session 可见；缺少日期隔离。首次历史回填按已接受的 Announcement-Aligned Financial History 使用并说明证据有限，不能声称完整 PIT。
- [x] 同逻辑记录、同公告日后见更正最早从首次观察后的可用 Session 生效；真实新披露日期保留来源证据。无法确定次序的冲突隔离，不用响应顺序、哈希或未验证的 update_flag 排序。
- [x] Financial Refresh 通过公告发现触发股票重查，并有有界历史更正核对及独立 reconciliation watermark。目标未返回时保留指标来源 pending；三表成功、无变化或已完成不能清除该 pending。
- [x] 权限不足、限流、超时、截断和缺列保留未完成状态，重试恢复不丢旧证据。区分采集未完成、来源缺失和不适用；供应商字段为空不从三表反算补上。
- [x] 财务指标保持稀疏版本，按每个字段固定期间选择最新可见报告，再取该列；选中空值不回溯旧非空值。百分数按证据转为小数，倍数保持原尺度；读取只投影需要的列、股票和时间。
- [x] 家族仍通过单一 Head 随 Financial Refresh 发布；刷新和恢复保留其他家族及真实覆盖。已接入 6 项在目录、Financial 区块、补全、HTTP/MCP 和 Agent 中一致，整类不能在指标未齐时显示全部 ready。
- [x] 在固定 Generation 上演示 roe 等指标从查询到研究完成；覆盖公告可见性、后见修订、独立 pending、截断重试和指标未就绪拒绝。ResearchRun、Batch、DailyTrack 值一致，研究禁用供应商网络仍完成。
- [x] 保存首批有界真实来源资格与脱敏请求证据；完成相关公开模块、真实 Worker/存储、合同和页面验证。新增来源直接采用当前数据合同，不增加版本迁移、vXX 升级链或兼容分支；保留已有来源和研究引用。

**Verification:** 母规格 T02、T06、T08、T09、T10、T11、T15。163 项全量作者入口由 06 补齐，完整历史覆盖由 07 汇总；本票不单独上线。

## Comments

- 2026-09-12：用户确认发布工单。已纳入最新的串行执行、每票 Plan / 验收 / 审查修复复审 / tracker / 独立提交，以及不兼容、不做版本迁移的要求。

## Plan — 2026-09-13

- 前置票 04 已独立提交为 5dc859f4，01—04 已完成；在同一已核实的隔离 worktree 串行实施本票。当前仅剩历史草案未跟踪，不纳入本票。
- 先核对普通 fina_indicator 的 167 列来源合同及六项单位/期间证据，再建立公开行为回归：100 行分片边界、同内容最早观察、无公告隔离、同公告后见修订、无序冲突及最新报告空值。复用原始响应存储，不伪造三表 report_type/comp_type。
- 实现指标独立稀疏版本及候选读取，显式请求全部源列，仅发布本票六项字段；按当前家族注册和 Generation 组合路径接入，保留非目标家族和冻结旧根。读取按实际字段/股票/Session 投影，比例转换有独立预期。
- 将指标采集接入既有 Financial Refresh：公告触发报告期重查、独立 pending、历史核对 watermark、失败恢复及候选发布。先检查现有持久化边界，直接修改当前合同，不引入兼容或版本迁移链。
- 贯通目录、现有 Financial 区块、HTTP/MCP、Agent 与 Run/Batch/Track；在隔离真实存储和 Worker 上验证缺失、修订、刷新保留及冻结 Generation，保留有界来源资格证据。完整历史采集仍在 07。
- 验收按受影响边界执行公开模块测试、真实依赖及浏览器检查，记录首次失败和修复结果。随后串行 Standards → Spec 审查，修复复审至无待办，更新 tracker 并独立提交，再开始 06。

初步代码核查：Generation 的财务引用、读取 resolver 和家族顺序仍显式处理 financial_pit；指标需作为自身家族贯通，不能将其伪装为三表。现有 financial_collection 和 daily_financial_refresh 包含三表分片/进度结构，实施前继续确定可复用的存储和发布边界。

## Report-period source adapter — 2026-09-13

- Rechecked the ordinary source documentation (https://tushare.pro/document/2?doc_id=79): single security, 100-row cap, date-based repeated requests. Existing statement adapter uses pagination, so indicator collection has an explicit report-range adapter rather than inheriting that assumption.
- Added six regression cases first; initial collection failed because the new module did not exist. Implemented explicit 167 source columns, bounded date subdivision, preserved capped parent receipts, and rejection when a single report date is still capped. Invalid columns, row widths, identity or out-of-range periods cannot become complete shards. Announcement nulls remain raw evidence for subsequent quarantine.
- The iterator must be exhausted by its collection owner; empty source responses do not prove an outstanding disclosure target satisfied. Persistence, resume and disclosure pending are not implemented by this adapter alone.
- New and existing statement adapter tests: 12 passed / 0.07 seconds, JUnit /tmp/thesistrace-issue05-source.xml. First Ruff run found three long test lines; formatting fixed them and final Ruff passed. No source network request, Head mutation or production collection performed.
- Next: durable indicator receipts and observation versions, then candidate/resolver, refresh pending/reconciliation, six-field catalog and consumer acceptance. Ticket remains incomplete and uncommitted; 06 has not started.

## Durable observation groundwork — 2026-09-13

- Added public regression tests before the observation module; initial run failed on the missing module. FinancialIndicatorObservationStore now reuses RawFinancialBatchStore and its immutable, checksum-verified addressed files rather than creating another raw storage implementation.
- Indicator version projection records raw source values, announcement/report dates, content hashes and earliest UTC observations. Same-content receipts deduplicate independent of input order; first historical values align after announcement, later same-announcement changes align after Shanghai observation date. No report_type/comp_type is fabricated; missing announcements and simultaneous conflicting values are quarantined.
- Reopen/duplicate, later revision and quarantine regressions: 3 passed / 0.28 seconds; Ruff format/check passed. This is module-level filesystem evidence, not proof of collection resume, publication or research integration.
- Remaining before acceptance: persist request/shard scope and resumable completion, integrate conflict transitions into actual series selection (including later conflicts and repeated/reverted values), candidate and family registration, independent refresh pending/reconciliation, six-field qualification and all consumer verification. No acceptance checkbox marked complete, no ticket commit, no work on 06.

## Observation transition regression fixes — 2026-09-13

- Two new regressions initially failed: global content deduplication swallowed a 2 → 3 → 2 reversion, and removed a previously seen value from a later simultaneous conflict. Reworked projection to group observations by timestamp and collapse only consecutive identical content sets.
- Preserved first_observed_at as earliest content provenance and added observation_event_at for actual transitions. Quarantined conflicts now carry state_effective_session so the eventual resolver can invalidate an earlier value at the right session; they never gain effective_available_session. A subsequent unambiguous observation may resolve the conflict without backdating it.
- Verified Shanghai date rollover, explicit null revisions and lack of update_flag winner ranking. Current evidence/adapter group: 13 passed / 0.08 seconds, /tmp/thesistrace-issue05-observation-transitions.xml; Ruff passes. These prove projection boundaries only; actual resolver/candidate and refresh integration remain outstanding.
- Ticket 05 remains in progress without acceptance completion or commit. Next implementation must consume state transitions in sparse reads and persist request/shard progress; 06—08 remain untouched.

## Sparse indicator reading — 2026-09-13

- Added the six ticket field definitions alongside the existing centralized Data definitions. Their source-unit contracts require the ticket's remaining independent qualification; they are not yet added to FIELD_DEFINITIONS or declared available by any Generation. No second authoring catalog or feature switch was created.
- Implemented FinancialIndicatorSeriesResolver on a frozen family/table reader: requests project only selected source columns and metadata, and sparse states are processed per instrument. It selects the newest visible report before taking the requested column, preserves explicit missing/conflict states, and prevents corrections to older reports from replacing newer reports. Percentage source values use decimal ratios; other scales remain unchanged.
- Three regressions first failed on the missing resolver module; implementation now passes latest-report null/conflict/recovery, older-report correction, and different-Generation rejection. Combined adapter/evidence/series suite: 16 passed, JUnit /tmp/thesistrace-issue05-series.xml. Ruff found one long field definition line, fixed; final Ruff passed.
- Still outstanding: request receipts/resume, candidate storage and family integration, actual Financial Refresh pending/reconciliation, source qualification, directory/HTTP/MCP/Run/Batch/Track/browser acceptance and serial review. This is an intermediate implementation, not completed ticket 05; no commit or work on 06.

## Resumable request receipts — 2026-09-13

- Added checkpoint regressions first; initial collection failed on the missing FinancialIndicatorCheckpoint. Implementation stores content-addressed request receipts scoped by collection key, with references to the existing immutable financial observation store. Reopening validates checksums and exact request scope, preserving the saved observation timestamp.
- Same-operation requests replay without provider access; a different operation observes again. Interrupted capped parents remain receipts and are excluded from accepted leaf observations; replay resumes date splitting. Unsupported endpoints and malformed receipt scope are rejected. The owning refresh must hold the mounted-data mutation lock and exhaust required shards before declaring completion; individual receipts do not prove disclosure targets satisfied.
- Three checkpoint cases and the existing indicator adapter/evidence/series cases pass: 19 passed, JUnit /tmp/thesistrace-issue05-checkpoint.xml. Ruff passes. These are local filesystem/source-boundary tests, not a claim of completed persistent Financial Refresh or actual supplier qualification.
- Next: persist the collection's completed targets/lineage and independent pending/reconciliation, construct immutable candidate partitions and integrate the family into Generation reading/publication; complete six-field qualification and consumer acceptance before serial review and commit. Ticket 05 remains incomplete, 06 not started.

## Immutable sparse candidate groundwork — 2026-09-13

- Added raw observation → candidate → reopen → selected-column Series regression first; missing module initially failed. FinancialIndicatorCandidateStore now reuses AddressedFileStore, canonical JSON and pinned ParquetWriterContract, stores instrument partitions with all 167 source columns and version metadata, and preserves raw observation references. Identical inputs produce the same candidate digest. It does not mark source completeness or publish a Head.
- New unknown-identity regression then failed because unmatched source rows were silently excluded. Build now rejects any source identity absent from the historical identity mapping. Combined indicator adapter/evidence/checkpoint/series/candidate suite: 21 passed, /tmp/thesistrace-issue05-candidate.xml; Ruff passes.
- Remaining candidate work before acceptance: strict manifest/partition/lineage validation, bounded full-history preparation, collection completion evidence and publication family contract integration. Current draft reads sparse selected columns but is not yet a publishable family or connected to Financial Refresh. Source qualification and consumer acceptance/review remain outstanding; ticket 05 not complete or committed, 06 not started.

## Candidate validation — 2026-09-13

- Added invalid-reference regression first, failing on the missing validate entrypoint. Candidate reopen now validates calendar, identity mappings, unique source references and bounded partition descriptors. Partition reads verify checksum, byte count, Arrow schema, row count and instrument ownership while preserving selected-column projection.
- Full candidate validation reopens retained observations and regenerates deterministic partition identities without writing data, comparing them with the manifest. This rejects omitted/extra/misbound partitions rather than treating a valid content hash as proof of source lineage. Build and validation share the same partition projection routine.
- Valid candidate plus duplicate partition, foreign identity, wrong count, missing observation and dropped partition checks pass: candidate suite 3 passed / 0.93 seconds. Initial Ruff import-order/line-length findings corrected; final Ruff and diff check pass.
- This validates candidate content/structure, not source collection completeness, publication readiness or full-history performance. Bounded large-history preparation, family/refresh integration, six-field qualification and end-to-end consumer acceptance remain before ticket 05 review and commit. No work on 06.

## Independent durable indicator progress — 2026-09-13

- Inspected the current three-statement announcement trigger and attempt tables: their resolution semantics are statement-owned. Added indicator-specific report targets and reconciliation progress to the current Data schema, without migration/version dispatch or changes to shared development storage.
- FinancialIndicatorProgressStore idempotently records report/announcement targets, retains unmatched targets after successful queries, resolves only matching report periods with sufficiently recent source announcements, and independently advances its reconciliation watermark. Updates to watermark and resolved targets share one database transaction. Collection integration must supply validated, retained and unambiguous observations; this store does not prove source completeness by itself.
- New integration regression first failed on the missing module. Ran the repository's isolated PostgreSQL/RustFS/Auth integration runner, run 20260912t195601z-77879-267b9e5d: 1 passed / 0.32 seconds, 482 deselected, process45998 exit0 and resources removed. No dependency restart phases included. Ruff passes.
- Next required step: wire actual announcement discovery and exhausted indicator collection to this state, including bounded reconciliation request ranges, pending retries and publication candidate lineage. Family/Generation integration, source qualification, consumer acceptance and serial review/commit remain outstanding. Ticket 05 incomplete; 06 untouched.

## Collection-to-progress integration — 2026-09-13

- FinancialIndicatorCollector now validates one historical identity's report-date range, persists required report targets before requesting data, exhausts the date-sharding adapter through immutable checkpoints, and writes a completed-range evidence receipt referencing retained observations. Only unambiguous, valid source report/announcement pairs resolve pending targets; a source failure leaves targets and previous reconciliation state intact.
- Collection uses the mounted-data mutation lock and a per-instrument database advisory lock, preventing concurrent writers from conflicting on the same request receipts. Identical retry requests reopen saved responses and retain the same evidence/result, even with provider access unavailable.
- First direct integration attempt skipped because no isolated runtime was configured; not counted as a pass. After moving the new service import to collection time, missing-module red was confirmed. Final repository isolated run 20260912t195906z-79315-cd309a3b: 2 passed / 0.28 seconds, process54731 exit0 and containers/volumes removed; no restart phases. Initial formatting findings fixed, final Ruff passes.
- Remaining: actual DailyFinancialRefreshService discovery scheduling (including unknown report periods and historical reconciliation ranges), candidate/Generation publication integration and lifecycle retention, source qualification, consumers, serial review and commit. The collector must receive the raw indicator provider, not the statement pagination wrapper. Ticket 05 remains incomplete; 06 not started.

## Generation integration boundary — 2026-09-13

- Inspected Generation family ordering, root validation, family readers and coverage descriptors. Current full validation assumed the statement family was the last reference. Replaced that positional lookup with the existing family-identity lookup, so adding another family cannot redirect statement manifest validation to a different reference.
- Existing financial candidate/Generation validation suite: 56 passed / 12.94 seconds, /tmp/thesistrace-issue05-family-lookup.xml, process29712 exit0; Ruff passes. This is a prerequisite refactor, not completed indicator Generation support.
- Remaining integration seams are explicit: extend accepted family identity/order and reference validation, attach the indicator resolver, validate its coverage against the frozen market calendar, and preserve it through Market/Financial/Industry composition and lifecycle scans. Candidate content validation alone cannot assert source coverage; completed collection-range evidence must be attached and verified before publication availability is declared.
- Ticket 05 remains uncommitted/incomplete. Do not begin 06 or claim the six indicator fields are available yet.

## Collection evidence gates candidate construction — 2026-09-13

- Added completed-request evidence validation regression first, failing on the missing validator. Each leaf now binds exact endpoint/fields/security/date parameters to its retained observation digest. Verification requires non-overlapping contiguous coverage of the declared report-date interval, all 167 columns, fewer than 100 rows per leaf, and source identities/report dates within that leaf. Capped parents cannot qualify as completed leaves.
- Collector validates the sealed evidence before recording reconciliation. Candidate build now requires collection_evidence_sha256s; removed its raw-observation-only entrypoint. All candidate identities require collection evidence, and full candidate validation checks that its observation references are exactly derived from that evidence. Existing test callers updated to the current contract; no fallback or alternate version path introduced.
- Candidate/checkpoint module group: 7 passed / 0.96 seconds; Ruff passes. Actual collection/progress isolated rerun 20260912t200504z-81197-13da5496: 2 passed / 0.29 seconds, process40238 exit0, containers/volumes removed. No dependency restart phases.
- Still needed: prove evidence dates cover the declared research range and pre-start semantics when composing a Generation, preserve full-history scaling/lifecycle, wire daily discovery/reconciliation scheduling and all consumers, source qualification and serial review/commit. Ticket 05 remains incomplete, 06 untouched.

## Candidate coverage and family reference — 2026-09-13

- Added coverage regression first: candidate construction incorrectly accepted missing history and a candidate ending after the collected report range. It now checks each identity's union of completed request intervals from the existing FINANCIAL_HISTORY_FLOOR through the candidate's final research session. Reuses retained overlapping collections without treating each incremental query as a fresh full-history requirement.
- First implementation rerun exposed a missing sessions argument in full validation; fixed the caller. Candidate regression group now 4 passed / 0.88 seconds; final Ruff passes.
- Candidate manifests now explicitly declare their own field_ids. Validation accepts only a nonempty unique subset of currently supported indicator fields, allowing stored field subsets to retain their original declaration when the catalog grows. No runtime version branch introduced.
- Added validated indicator family_reference binding the candidate digest/byte count, six field identities, sparse version table, source-evidence coverage and limited revision description. The reference is not yet composed into a Generation or published; source qualification/pending presentation are still separate required gates.
- Next: wire this reference and resolver into Generation composition, root validation, consumer field admission and lifecycle retention, then finish daily refresh scheduling and source qualification. Ticket 05 incomplete/uncommitted; 06 untouched.

## Indicator Generation composition and reading — 2026-09-13

- Added a complete in-memory/filesystem market → indicator candidate → composed Generation → Series regression first; missing composition entrypoint failed. Implemented current indicator family order/reference validation, candidate composition, historical identity/calendar matching and sparse reader registration. Replacements must retain prior observation references.
- Registered the six definitions in the single current Data catalog. Family descriptors carry explicit field_ids for the indicator candidate; root projection validation uses these owned declarations alongside existing family/catalog declarations. Old roots still lack indicator fields and reject their use; no version or fallback path introduced.
- Intermediate failures exposed an incorrect historical identity method name and root projection validation ignoring the new family's fields. Corrected both. Formatting was limited to changed functions and the new test; Ruff passes.
- New Generation plus existing financial candidate/mounted store group: 126 passed / 20.99 seconds, /tmp/thesistrace-issue05-generation.xml, process3247 exit0. Extended new regression then verified row/columnar equality and old-root rejection: 1 passed / 1.28 seconds. Original root descriptor remains exactly unchanged.
- This is local composition/read support, not completed Head publication or production readiness. Remaining: independent source qualification, daily discovery/reconciliation scheduling, lifecycle/GC and refresh retention for the new family, admission/overview/HTTP/MCP/browser/Run/Batch/Track acceptance, updated catalog fixtures, serial review and commit. Ticket 05 incomplete; 06 untouched.

## Indicator lifecycle retention — 2026-09-13

- Candidate JSON/Parquet now use the existing manifests/objects addressed stores. Generation reference traversal retains indicator candidate manifests, partitions, raw observations and completed collection ledgers; the generation/candidate regression verifies all references appear in the existing inventory. No additional physical file kind or parallel garbage collector was introduced.
- Added failing checkpoint-retention regression, then included immutable request receipts in the garbage collector's retained graph. Both completed leaves and capped parents survive interrupted collections; receipt checksums and collection/request path scopes are verified, and missing/corrupt evidence fails validation rather than permitting collection.
- Added collection-ledger roots from indicator reconciliation and resolved report targets. These expand to the ledger and its validated raw leaf observations. This SQL retention path still needs a dedicated completed-collection integration assertion; checkpoint preservation does not prove it independently.
- Corrected a missing import exposed by the first implementation rerun and fixed Ruff import ordering. Candidate/Generation/checkpoint tests: 10 passed / 1.18 seconds. Extended capped-parent assertion: checkpoint group 5 passed / 0.41 seconds. Ruff and git diff --check passed.
- Real isolated garbage collection test: 20260912t202445z-96256-9ea4f440, 1 passed / 0.38 seconds, process 3237 exit 0. It deletes an unrelated unrooted raw object, retains an unpublished indicator checkpoint and resumes that request with a provider that rejects any network access. Runner removed its containers and volumes. No shared development data changed; dependency restart phases were not run.
- Remaining ticket 05 work includes completed-ledger/candidate publication retention, daily discovery/reconciliation scheduling, source qualifications, full-history resource bounds, consumer/admission/browser/Run/Batch/Track acceptance and serial reviews. Ticket remains incomplete and uncommitted; 06 has not started.

## Completed evidence retention and invalid announcement regression — 2026-09-13

- Added a real GC assertion for two completed collections: the first ledger remains rooted by a resolved report target after reconciliation advances to the second ledger. Both ledgers and their leaf observations reopen and validate after collection. Isolated run 20260912t202700z-97269-7d5fd972: 1 test, 0 failures/errors/skips, JUnit suite time 0.350 seconds; process 29577 exited 0 and removed its containers/volumes. This closes the prior unverified SQL ledger-retention seam.
- Added a regression proving a source announcement earlier than its report end was incorrectly marked available. Projection now retains that source row with invalid_announcement status and no effective session, consistent with collector rejection; no past value is fabricated. Evidence/series/candidate/Generation group: 16 passed / 1.05 seconds. Ruff and diff whitespace checks pass.
- Inspected actual refresh integration: DailyFinancialRefreshService owns discovery receipts, statement candidate construction and publication; DataRefreshService passes sources from data_operator. Existing FinancialAnnouncement.report_period is nullable, but the initial indicator progress store requires a known period. The next integration must retain independent indicator targets for unknown-period correction announcements rather than guess a quarter or let successful statement processing clear them. Ordinary report-range parameters must not use the announcement discovery interval as a provider cursor.
- Daily scheduling/publication, consumer acceptance, source qualifications and serial review/commit remain required. No ticket completion or production readiness is claimed.

## Daily discovery integration plan — 2026-09-13

- Extend the current indicator target contract to retain nullable report periods, using PostgreSQL NULLS NOT DISTINCT uniqueness for deduplicated unknown-period targets. No guessed period, alternate schema version or migration branch.
- Record independent indicator targets in the same transaction that persists financial announcement discovery. Statement acceptance never resolves those targets. Known periods resolve only against matching retained indicator reports; an unknown-period correction remains pending until its target can be established, rather than being cleared by an unrelated row or completed request.
- Reuse this pending inventory for the daily indicator scheduler, including retries and bounded historical reconciliation. Keep report-period query bounds independent from discovery announcement-date bounds. Verify transaction persistence, duplicate unknown targets and independence from statement acceptance with the isolated runner before wiring publication.

## Independent indicator discovery targets — 2026-09-13

- Unknown-period target regression first failed with TypeError from date.fromisoformat(None), isolated run 20260912t202948z-98539-d31b4f7f, process 85693 exit 1; this was the expected missing current-contract behavior, not a dependency failure.
- Indicator targets now retain nullable report periods with NULLS NOT DISTINCT uniqueness. Duplicate unknown-period announcements produce one target. Reconciliation only resolves matching known report periods; unrelated reports cannot clear unknown targets. Collector input/output types preserve nullable targets without inventing a date.
- FinancialDailyRefreshStore.record_discovery writes indicator targets in its existing discovery transaction using the shared target-recording function. Existing statement attempts continue owning their separate trigger status; no statement-success path resolves indicator targets.
- Isolated verification 20260912t203131z-99265-1a730e3a: 4 passed / 0.50 seconds, process 83466 exit 0, cleanup completed. Covers unknown-period deduplication/preservation, known-period matching, collector failure/retry and actual statement acceptance leaving the indicator target pending. Ruff and diff whitespace checks pass.
- Remaining: the targets are now populated by daily discovery, but provider dispatch, bounded historical reconciliation selection, persisted indicator candidate publication and aggregate readiness are not yet wired. Do not describe discovery target creation as completed daily indicator refresh.
- Additional transaction regression passed: 20260912t203303z-231-46b993d9, 1 passed / 0.27 seconds, process 39389 exit 0 and cleanup complete. An invalid later identity rolls back an earlier valid unknown-period target; retrying valid discovery twice commits exactly one target. Ticket 05 remains incomplete/uncommitted; no subsequent ticket has started.

## Daily indicator dispatch plan — 2026-09-13

- Add a durable per-refresh dispatch plan: all eligible independent pending instruments plus a bounded rotating historical reconciliation batch, using the frozen historical identity map and target date. Rotation must continue past repeatedly failing instruments; successful-query watermarks alone cannot schedule fairly when a source remains unavailable.
- Persist the selected work before source calls so retries do not select a different batch after some targets resolve. Each instrument reuses the existing request checkpoint under an operation/security key, fully exhausts bounded report-date shards, records its own completed ledger, and preserves failures/pending independently.
- The dispatcher returns completed evidence and explicit source failures to the daily service. Candidate coverage remains based on verified evidence; dispatching a batch cannot by itself mark unqueried history/current sessions ready. Subsequent publication wiring must retain previous evidence and respect actual coverage.

## Durable daily dispatch and source recovery — 2026-09-13

- Added FinancialIndicatorDailyCollector over the existing single-security collector. It freezes the historical identity/target/session-index scope and selected pending-plus-background instruments in an addressed Operator receipt before network calls. Reusing an operation with a different scope is rejected; retrying it retains its original work after targets resolve.
- Historical reconciliation rotates across the frozen universe using Research Session index and a bounded batch (default 64), independent of successful-query watermarks. Persistent failures cannot hold the background cycle at the same instrument. Pending announcements are always included separately; unknown periods remain explicit pending. Date-filtered targets do not import future disclosures into the current dispatch.
- Returns completed collection ledgers, explicit per-instrument source failures and remaining pending IDs. Ordinary source calls still exhaust report-period shards from the retained history floor to target; request checkpoints resume successful leaves offline. Ownership is checked between instruments. This result does not declare candidate coverage or readiness.
- Red: 20260912t203533z-7832-4cf185cc failed on the missing dispatcher import (process 33536 exit 1). First implementation 20260912t203756z-11188-f4cef9f2 exposed a real connection-pool timeout after 30 seconds: outer dispatch locks overlapped the inner collector's locks and progress transaction. Restricted dispatch locks to plan creation instead of increasing pool size; individual collections retain their own mutation/identity fences.
- Final isolated test 20260912t203921z-12035-87600785: 1 passed / 0.52 seconds, process 92043 exit 0 and cleanup complete. Verifies a failed pending instrument, successful background work, rotation to the next historical security despite persistent failure, same-operation scope rejection, recovery, fixed selection and offline completed replay. Ruff and diff whitespace checks pass.
- The dispatcher is implemented and independently verified but not yet invoked by DailyFinancialRefreshService. Next connect the raw indicator provider from data_operator/refresh into this dispatcher, persist its candidate/publication state and aggregate pending/readiness without falsely extending evidence coverage. Source qualification and consumer/Browser/Run/Batch/Track gates remain, followed by serial reviews and the ticket's independent commit. Ticket 05 remains incomplete; 06–08 untouched.

## Daily service and Worker source wiring — 2026-09-13

- Added the required indicator_provider contract to DailyFinancialRefreshService. DataRefreshService carries this provider through financial claims, and data_operator passes the original raw provider rather than the statement adapter. Financial workers reject a missing indicator provider; market/industry dispatch does not require one.
- After persisted announcement discovery, daily refresh now invokes the durable indicator dispatcher with frozen historical lifecycles and the target's Research Session index. Historical delisted identities remain eligible. Completed dispatch results persist once in financial_daily_refresh_operations.indicator_collection and are reused on recovery. Operation result ledgers also participate in GC retention until the operation releases retention.
- Added actual daily-service regression asserting that the saved indicator collection ledgers reopen and validate. Red run 20260912t204252z-14053-48f1c9a1 failed on the missing constructor keyword; direct-service implementation run 20260912t204455z-15092-9e441c9f passed (JUnit suite 1.294 seconds, process 33367 exit 0).
- Extended that regression with the outer mounted-data fence held by the Worker. Run 20260912t204600z-15908-41c3c14c reproduced PoolTimeout after 30 seconds. Combined the shared mounted-data fence and exclusive indicator work lock on one PostgreSQL connection, retaining both lock modes and closing partially acquired sessions on failure. Did not increase pool capacity or remove lifecycle protection.
- Final isolated run 20260912t204744z-16619-581299bb: 6 passed / 1.30 seconds, process 16068 exit 0 and cleanup complete. Includes outer-fenced daily refresh, dispatch recovery/rotation, cancelled acquisition and backend-loss cleanup for both ordinary and mixed lock sequences. No real supplier/network qualification is implied by these fixtures.
- Still required: persist/build/compose the indicator candidate into the same Head publication; aggregate indicator failures/pending/coverage in current readiness and operation results; update remaining financial process_next test callers and Replay source bundles for the required provider contract; verify operation-result retention and recovery; source qualification, resource bounds, catalog/HTTP/MCP/Agent/browser/Run/Batch/Track gates, serial review and independent commit. Current successful statement publication is not evidence that the six indicator fields were published. Ticket 05 remains incomplete; 06–08 untouched.

## Indicator candidate publication plan — 2026-09-13

- Persist every completed indicator collection ledger append-only, in addition to the latest reconciliation watermark. Candidate construction must retain pre-publication observation history as well as prior published candidate evidence; latest-only reconciliation cannot prove the earlier observed state.
- Determine the common verified research prefix across the frozen historical identities. Build only that supported range; an uncovered identity yields no new candidate, and an older complete prefix cannot be relabeled through the current target. This conservative source-range gate remains explicit until current discovery evidence is incorporated into coverage advancement.
- Persist an indicator candidate on the same financial daily operation, retain it before CAS, and compose it with the statement candidate before the existing one-Head publication. On competing indicator updates verify the prior reference instead of overwriting a new family with stale evidence. Existing publication-coordinate recovery must correspond to the combined root.

## Published indicator family and evidence history — 2026-09-13

- Candidate coverage now derives the continuous research prefix verified for every frozen historical identity. Added regression for a later uncollected session and an entirely uncollected identity. Corrected the test's initially invalid empty-row helper usage; final candidate group 5 passed / 0.93 seconds. Full indicator candidate/Generation/evidence/series/checkpoint group: 22 passed / 0.90 seconds.
- The module regression also exposed a circular import introduced by the previous source-wiring change. Raw provider/result types now use TYPE_CHECKING; runtime collector import occurs at the call boundary. This preserves the current contract without a fallback.
- Added append-only financial_indicator_collections, linked to the per-instrument reconciliation owner. Every completed ledger is indexed even before any candidate is published; later reconciliation cannot discard an earlier observed version. GC retains this history. Strengthened the ledger GC regression so the older ledger has no report-target reference and therefore relies on the append-only history.
- Daily refresh builds the indicator candidate from retained history plus prior published evidence, saves its manifest on the same operation, and composes it with the statement candidate before the existing CAS. Prepared indicator candidates participate in operation retention. Insufficient verified common coverage does not manufacture a current-range candidate.
- Publication regression first failed on missing financial.indicator.eps (20260912t205429z-19578-bf5101d0). Implementation run 20260912t205628z-20349-e203311a published the family and read the expected prior-quarter eps=1.0 on the announcement day, then failed because Overview assumed every financial family had statement coverage. Updated family description to interpret coverage contracts rather than the financial category alone.
- Combined run 20260912t205851z-21156-1e9e1a7a passed publication/reading/Overview but exposed cross-test database records pointing at the previous test's different temporary mount. Updated the two new GC tests to use the existing drop_product_schemas helper before/after their own isolated setup, preserving production validation and shared development data.
- Important remaining coverage work: the current raw report-range prefix is deliberately conservative. Integrate saved announcement-discovery evidence and independent unresolved indicator targets into daily coverage advancement; otherwise a rotating historical batch would leave the family artificially behind the market. Also freeze indicator pending/failures into readiness and verify combined-family publication recovery/concurrent target changes before declaring this ticket complete. Source qualifications, resource bounds, remaining consumer/Replay adaptations, browser/Run/Batch/Track gates and serial review/commit remain outstanding.

- Final combined verification 20260912t210021z-21788-3c1ec279: 2 tests, zero failures/errors/skips; JUnit suite 1.983 seconds. Process 56893 exit 0 and cleanup complete. Proves real isolated publication/read/Overview plus retention of an older untargeted collection ledger. Ticket remains incomplete/uncommitted; 06–08 have not started.

## Frozen indicator readiness plan — 2026-09-13

- Freeze unresolved source identities/dates with the indicator candidate, independently from statement readiness. Report raw evidence coverage separately from the complete-through session usable for admission; an unresolved disclosure blocks the indicator family after its announcement date, consistent with next-Session availability.
- Carry that boundary through family reference validation, Overview and dependency admission. Keep older verified ranges and unrelated price/statement families available. Aggregate Financial readiness from the actual supported families, not only the statement candidate.
- Daily candidate building combines its saved per-instrument failures with unresolved disclosure targets through the operation target date. Preserve these frozen facts for retries; mutable future progress must not rewrite a published candidate's readiness.

## Frozen coverage and aggregate readiness verification — 2026-09-13

- Frozen indicator candidates now retain unresolved identities and earliest unresolved source dates. Family references distinguish verified source range from the complete-through Session; dependency admission excludes an indicator family with no complete Session while retaining price coverage. Daily candidate construction freezes pending targets and dispatch failures rather than deriving publication readiness from later mutable progress.
- Previous test process 22995 was no longer available, so verified the affected candidate/Generation group again: 6 passed / 1.09 seconds (15342 exit 0). This is fresh verification, not an inferred result for the missing process.
- Corrected Overview's financial summary to aggregate every supported financial family. No available financial fields means not_ready; an absent/partial family or discovery gap means ready_with_gaps; otherwise pending is retained and ready requires all families ready. Uses the existing response status vocabulary and existing four Data sections.
- Added the aggregate readiness regression first: failed collection on the missing function (exit 2). After implementation, readiness plus candidate/Generation tests: 13 passed / 1.13 seconds (62490 exit 0), Ruff passed. Updated the statement-only publication expectation to report the missing indicator family as a gap.
- Real storage/publication verification is running under isolated run 20260912t211147z-25660-e5ee086b, process 12289; terminal outcome still required. Ticket 05 remains incomplete and uncommitted. Coverage advancement from saved discovery evidence, recovery/concurrency, source qualification, resource bounds, remaining consumer gates and serial review are still outstanding.

- First real-storage run 20260912t211147z-25660-e5ee086b: 2 passed, 1 failed, process 12289 exit 1 and cleanup complete. The remaining assertion expected ready despite the fixture's period-less announcement remaining pending for indicators. Preserved that pending behavior and asserted both aggregate and indicator-family ready_with_pending; statement readiness remains independently ready.
- Final affected run 20260912t211232z-26072-6ce2b798: 3 passed / 2.87 seconds, process 66362 exit 0 with isolated resource cleanup complete. Covers statement-only publication reporting the absent indicator family, combined publication retaining indicator pending and expected announcement-day values, and append-only ledger GC retention. No source qualification, consumer-wide acceptance or ticket completion is inferred.

## Combined publication target guard plan — 2026-09-13

- Compare the current indicator family with the operation's frozen source family before composing a prepared indicator candidate. A concurrent indicator publication must not be overwritten merely because its observations happen to be a subset of the stale candidate; pending state and coverage are also publication truth.
- Recovery by financial publication coordinate must validate both the statement candidate and the indicator candidate expected by the operation. An inherited statement coordinate alone is insufficient if another indicator publication changed that family.
- Add a real isolated publication race regression by moving Head to a different indicator candidate after preparation, then assert the original operation refuses the stale publication and leaves the concurrent family intact. Preserve existing successful publication and independent family readiness checks.

- Race regression setup exposed two fixture isolation problems before reaching product behavior: shared durable operation IDs (20260912t211438z-27418-37a1306a, 26720 exit 1), then append-only indicator ledger references into another parameter case's mount (20260912t211529z-28100-73ce178f, 73529 exit 1). Cases now use distinct IDs and the existing isolated schema setup/cleanup, preserving production validation.
- Confirmed product red in 20260912t211623z-28542-ccc1ba67: the competing indicator Head was published, but the stale operation did not raise and overwrote it (16462 exit 1, cleanup complete).
- Added indicator target identity verification before composing a prepared replacement. Current family must still match the frozen source or the exact prepared candidate; a different concurrent family raises FINANCIAL_INDICATOR_TARGET_CHANGED. When no indicator replacement is prepared, unrelated indicator publications remain preserved.
- Verification running: 20260912t211726z-29220-12437cd8, process 56851. Ruff reported test formatting issues to fix after execution; no passing lint claim yet. Combined-coordinate recovery remains a separate outstanding boundary, not proven by this guard.

- Final target-guard run 20260912t211726z-29220-12437cd8: 2 passed / 2.90 seconds, process 56851 exit 0 and isolated resources cleaned. Confirms successful combined publication and refusal to overwrite a concurrent indicator candidate; competitor Head remains intact. Fixed the reported test import/line formatting afterward; Ruff and diff whitespace checks passed. Ticket 05 remains incomplete and uncommitted; recovery verification and the other listed acceptance boundaries still remain.

## Worker recovery and Replay indicator plan — 2026-09-13

- Existing real Worker recovery test currently fails FINANCIAL_WORKER_SOURCE_MISSING (20260912t211907z-30088-670adeb9, 30997 exit 1, cleanup complete). Update its explicit provider contract and assert the indicator family survives the successor market Head and recovery keeps the original publication receipt.
- Replay currently accepts only ts_code for financial raw queries. Add ordinary fina_indicator report-period filtering and its 100-row response cap within the existing financial response records, with strict request/date/identity validation. Retain the current replay format; no fallback or new version chain.

- Added current-format fina_indicator Replay over retained financial records: strict ordinary request keys, valid ordered report-period bounds, no dates beyond the recorded observation window, source identity validation, report-date filtering and a 100-row cap. Original response columns are retained. No new format version or compatibility branch.
- New adapter regression failed REPLAY_REQUEST_MISMATCH before implementation. After implementation all 11 Replay adapter tests passed / 7.94 seconds (89515 exit 0); Ruff passed for the adapter and affected tests.
- The daily financial Replay fixture now includes all 167 indicator source columns. Worker recovery test passes the same Replay as indicator_provider and verifies the successor Market Generation retains the exact published indicator family. Test owns its isolated schema/mount so append-only evidence cannot leak between tests.
- Real Worker recovery verification running under 20260912t212138z-31196-cb931ac1, process 99116; terminal outcome still required. Other process_next fixtures still need explicit source adaptation; this run does not cover the entire Worker suite.

- Worker run 20260912t212138z-31196-cb931ac1 failed the new indicator-family assertion (StopIteration; 99116 exit 1, cleanup complete). Retained dispatch evidence showed two historical securities, while Replay supplied only 000001.SZ. The missing second security correctly prevented a complete candidate; did not relax the source coverage gate. Added 000002.SZ to the indicator Replay records.
- Reverification running 20260912t212311z-32192-b1707c1b, process 23726. Separate remaining outcome issue to examine: canonical_changed currently compares only statement projections, so adding or changing indicator values may still be described as no_change. Do not infer combined source outcome correctness from recovery mechanics alone.

- Final Worker recovery run 20260912t212311z-32192-b1707c1b: 1 passed / 2.34 seconds, 23726 exit 0 and isolated cleanup complete. Proves the combined indicator family survives a subsequent Market publication, lost completion is reconciled to the original published Generation, recovery creates no replacement manifests and does not roll Head back. Ruff and diff checks pass. This does not yet prove recovery after an indicator-family successor or the correctness of combined canonical_changed/outcome reporting. Ticket remains incomplete/uncommitted.

## Combined canonical outcome plan — 2026-09-13

- Financial refresh canonical_changed must include an indicator family's addition or projected version changes, not only statement tables. Compare the operation's frozen source indicator projection with its prepared indicator projection; preserve no_change for repeated identical observations and coverage/pending-only metadata updates.
- Reuse the existing sparse partition identity (including visible version facts) to avoid materializing daily series for an outcome check. Keep collection receipts and readiness metadata outside the projection identity. Use the same calculation for direct outcomes and recovered Worker receipts.
- Verify projection repeat/change semantics through immutable candidate construction, then update the real Worker recovery expectation: the first indicator publication is published even when statements did not change.

- Added indicator canonical projection identity over declared fields and immutable sparse partitions, excluding collection receipts and pending/coverage metadata. Regression failed on the absent method (62938 exit 1); candidate group after implementation: 6 passed / 1.28 seconds (59870 exit 0). Same-content observations and pending-only changes keep the projection identity; a later changed value changes it.
- Direct and recovered financial outcomes now compare the prepared indicator projection against the operation's frozen source family in addition to the statement projection. First addition is a canonical change even when statements are unchanged. No supplier reads or daily expansion are performed for the outcome check.
- Updated real Worker recovery expectation from no_change to published for its first indicator publication. Verification running 20260912t212629z-33753-32538718, process 15346. Ruff and diff whitespace checks passed; terminal Worker outcome remains to be recorded.

- Final combined-outcome Worker verification 20260912t212629z-33753-32538718: 1 passed / 2.30 seconds, process 15346 exit 0 and isolated cleanup complete. Recovered receipt now reports published for the first indicator family while retaining the original Generation and successor Head. Candidate repeat/change regression, Ruff and whitespace checks passed. Ticket 05 remains incomplete/uncommitted; pending/failure outcome aggregation, discovery-backed coverage advancement, remaining source/consumer qualifications and serial reviews remain outstanding.

## Remaining Worker source-contract plan — 2026-09-13

- Update financial Worker calls to pass the actual Replay indicator provider; interrupted/resumed attempts use their corresponding Replay bundle. Tests replacing the entire daily service provide an inert explicit provider, without adding a production default or fallback.
- Extend the existing per-test database initialization reset to indicator reconciliation/targets, matching its current statement-operation isolation. Completed indicator collections cascade from reconciliation; no shared development database is touched.
- Run the affected ordinary refresh, replay reselection, completion recovery, lease/heartbeat and failure-classification cases together. Preserve independent source failure behavior and update only outcome expectations whose meaning changed because indicators are actually first published.

- Adapted remaining real financial Worker calls to their actual Replay provider, including interrupted and resumed bundles. Fully mocked daily-service cases pass an explicit inert provider; one dispatch regression verifies the exact provider is forwarded in constructor options.
- Per-test financial database initialization now also resets indicator targets and reconciliation (with completed-ledger cascade), aligning durable records with each test's mounted evidence. No production initialization/reset behavior changed.
- Real Worker group 20260912t212825z-34798-54d2ef10: 12 passed / 7.60 seconds, process 61228 exit 0 with cleanup complete. Covers ordinary clean/degraded/changed refresh, replay reselection, successor-Head completion recovery, expired leases, heartbeat and failure classifications/filesystem retries. First indicator publication now correctly expects published in the clean case.
- Fixed a test-only duplicate keyword during dispatch fixture editing, and a long SQL string in reset helper. Ruff passes for both affected integration files. Mocked dispatch/outcome/failure group running 20260912t212944z-35474-7aa886eb, process 30907; terminal result still required. Ticket 05 remains incomplete/uncommitted.

- Final dispatch-contract group 20260912t212944z-35474-7aa886eb: 9 tests, zero failures/errors; JUnit suite 1.890 seconds. Process 30907 exit 0 and cleanup complete. Provider forwarding and clean/degraded/business/infrastructure outcomes remain verified. Remaining ticket gates include indicator pending/failure outcome aggregation, discovery-backed coverage advancement, source qualification, resource bounds, consumer acceptance and serial reviews.

## Combined pending/failure receipt plan — 2026-09-13

- A statement-complete refresh with indicator query failures must publish a degraded receipt, preserving failed indicator identities as unresolved work. Merge statement pending securities with the saved indicator dispatch pending/failure identities, deduplicating securities shared by both sources.
- Freeze aggregate counts/status in the existing published_outcome when completing the daily operation. Recovered outcomes read those persisted aggregate facts; do not retrofit indicator readiness into the statement candidate's independent coverage contract.
- Add a real Worker case with missing recorded indicator data for one historical security and otherwise clean statements. Expect degraded, one failed/pending security, and preserved prior data. Existing statement-pending cases also exercise cross-source deduplication.

- Red 20260912t213224z-36481-b75f4cbb: missing indicator source returned no_change instead of degraded (7564 exit 1, cleanup complete). Other four cases passed.
- Completion now merges unique statement pending/failed instrument identities with saved indicator pending/failures, persists counts and identity lists in published_outcome, and derives the daily status from aggregate pending plus discovery gaps. Statement candidate coverage remains independent. Direct and recovered results use the frozen aggregate counts; completed-operation inspection also reports the persisted failure count.
- First corrected run 20260912t213349z-37393-b510ba5b: 5 passed / 3.24 seconds, 19328 exit 0 and cleanup complete. Added an overlap case where both sources fail for the same security, expecting one failed/pending instrument, plus the existing direct pending-disclosure and successor-recovery cases. Their combined verification is running as 20260912t213446z-38076-2be0fbb4, process 19987. Ruff passed; terminal result still required.

- Final combined receipt verification 20260912t213446z-38076-2be0fbb4: 9 passed / 7.49 seconds, 19987 exit 0 and cleanup complete. Indicator-only failure degrades the Worker result; overlap with a statement failure is counted once; period-less indicator disclosure remains pending despite complete statements; target guard and successor-Head receipt recovery remain passing. Ruff and whitespace checks passed. Ticket 05 is still incomplete/uncommitted: discovery-backed coverage advancement, source qualification, bounded resource work, consumer-wide acceptance and serial review remain.

## Candidate memory scope plan — 2026-09-13

- Current build/validate load every raw observation into one list and then rescan it for every security. Replace that with a verified per-security observation-reference index derived from completed ledgers, and project one security at a time.
- Keep the existing immutable manifest/partition format and exact output semantics. Validate identity and all source columns per security; never mix securities in a shard. Release source payloads before loading the next security. This addresses whole-universe payload retention and repeated filtering; per-security history/version bounds remain to be evaluated separately.
- Add a public build/reopen regression that observes live decoded payload ownership across several securities and asserts payloads from distinct securities are not retained together. Existing deterministic projection and tamper tests verify unchanged results and evidence validation.

## Candidate streaming verification — 2026-09-13

- Fixed the new test helper's initial misuse of RawFinancialBatchStore.read (it already returns decoded records). Confirmed resource red: 4 security payloads retained concurrently (83129 exit 1). Per-security reference indexing/projecting then passed candidate plus Generation tests: 8 passed / 1.42 seconds (13839 exit 0).
- Strengthened the public build/validate test to four observations for each of four securities. It exposed per-security eager payload loading (4 live decoded payloads; 30663 exit 1). Candidate projection now consumes an observation iterator, validates each source payload before yielding it, and releases the per-security projection frame before loading another security.
- Indicator version grouping now stores one row per content digest and references that row from observation-time states, instead of retaining another 167-column dictionary for each repeated identical observation. Ordering/reversion/conflict semantics remain unchanged; metadata/address indexes and actual version history still scale with retained evidence, so this is not a claim of constant total memory for arbitrarily long history.
- Final candidate/Generation/evidence/series group: 19 passed / 1.44 seconds (10331 exit 0), including at most one security and two decoded payloads live during build/validate, exact multi-security read values, repeat/revision identity, conflict/reversion timing and tamper validation. Ruff and diff whitespace checks passed. No manifest format or version changes. Ticket 05 remains incomplete/uncommitted; discovery-backed coverage, source qualification, consumer acceptance and serial review remain outstanding.

## Six-field live qualification plan — 2026-09-13

- Rechecked official fina_indicator documentation (doc_id=79) and local credential availability without exposing credentials. Python 3.12.11 and the repository's existing transport are available; the optional tushare package is absent, so reuse the project adapter rather than install another dependency.
- Perform six bounded read-only requests: fina_indicator, income and balancesheet for 600519.SH and 000001.SZ, report periods 2023–2025. Indicator requests explicitly include all 167 columns; selected statement columns allow independent EPS, current-ratio, equity/share and profit-growth comparisons across annual/interim reports and an industrial/bank sample.
- Persist request parameters, observed time and raw non-secret results; preserve duplicates and ambiguities rather than picking a convenient row. Separate official period semantics, observed unit checks and unresolved applicability. No dataset Head, production state or supplier data is modified.

## Six-field source qualification evidence — 2026-09-13

- Six bounded official-source requests completed successfully (77442 exit 0): indicator/income/balance for industrial and bank samples, preserving all returned columns and duplicate rows. Indicators each returned all 167 requested columns, 16/15 rows and 12 distinct report periods. Source artifacts and scripts contain no credentials; no Dataset Head changed.
- Independent checks: EPS 11 matches with one ambiguous case; BPS/current ratio 6 industrial matches each; ROE, single-quarter ROE and parent-profit YoY 12 matches each, all within 0.0001 supplier units. Bank current-ratio source/operands are null. Bank BPS is not forced through the industrial simplified equity/share formula.
- Qualification report is indicator-pilot-qualification.md, raw evidence indicator-pilot-source-observations.json and comparisons indicator-pilot-unit-crosschecks.json. Observed units support the six existing field mappings and percent normalization. Same-announcement conflicting values (including bank EPS/BPS) are retained and excluded from ambiguous numeric comparisons; passing field unit checks does not bypass runtime whole-row conflict isolation.
- This closes the bounded six-field source-scale investigation, not full-history collection, universal applicability or PIT reconstruction. Ticket 05 remains incomplete/uncommitted; coverage advancement, consumer acceptance, remaining recovery/resource boundaries and serial review still apply.

## Indicator successor recovery acceptance plan — 2026-09-13

- Extend the existing real Worker lost-completion regression to publish a different indicator candidate before recovery, retaining the original operation coordinate. Use a readiness change on the same verified observations to distinguish candidate identity without inventing provider evidence.
- Require the recovered receipt to identify the original combined publication, preserve the successor Head, and create no new manifests. This verifies the durable Worker recovery route; the direct service coordinate-only shortcut remains a separate inspection boundary.

- Recovery acceptance run 20260912t215149z-44046-8ec7a287: 2 passed / 3.91 seconds; process 68848 exit 0 and isolated cleanup complete. Both Market successor and different indicator-readiness candidate preserve the successor Head while the recovered receipt identifies the original combined publication; recovery creates no new manifests. Ruff and diff whitespace checks passed. This closes the Worker successor-candidate case, not direct-service coordinate reconciliation, discovery coverage, consumer acceptance or full ticket review. Ticket 05 remains incomplete and uncommitted.

## Direct combined-publication recovery plan — 2026-09-13

- Exercise the same lost-receipt and successor-family fixtures through direct DailyFinancialRefreshService.publish before Worker receipt reconciliation. Require the original composed Generation identity, preserving successor Head and immutable manifests. Replace the coordinate-only completion shortcut if it assigns the successor identity to the old operation; reuse durable composed-publication evidence and existing reconciliation.

- Red run 20260912t215334z-45026-8ab890ab: both direct recovery cases returned the successor Generation instead of the original publication; 2 failed, 2 passed / 6.02 seconds, process 93669 exit 1 with cleanup complete.
- Direct retry now reconciles the stored composed Generation using the same receipt path as the Worker, instead of overwriting it with current Head. A durable head-moved marker also permits recovery after later coordinates change. Reconciliation verifies original operation coordinate, statement candidate and prepared indicator candidate before completing the receipt. No schema or compatibility change.
- Corrected run 20260912t215449z-45616-a53d2749: 4 passed / 5.55 seconds; process 10910 exit 0 and isolated cleanup complete. Market/indicator successors pass through both direct and Worker routes, retain successor Head and create no extra manifests. Ruff and diff checks passed. Ticket 05 remains incomplete/uncommitted; discovery-backed coverage advancement, remaining consumer/resource acceptance and serial reviews remain.

## Discovery-backed indicator coverage plan — 2026-09-13

- Retain immutable announcement-discovery receipts in the existing raw evidence store and reference them from the current indicator candidate. A receipt records the queried historical identity scope, interval, completed categories, gaps and discovered announcements; it does not claim another raw indicator query occurred.
- Extend a security's continuous historical collection prefix only across fully checked announcement intervals for that identity. Incomplete categories, interval gaps or missing initial history cannot advance coverage. Existing unresolved indicator targets still cap usable coverage independently, including unknown report periods.
- Preserve receipts through subsequent candidates and Generation retention. Daily discovery queries the historical identity scope so delisted identities are not silently omitted from the coverage proof. Add candidate boundary tests before integration acceptance; no version migration or alternate reader.

- Candidate regression first required a nonempty identity row for the existing fixture helper; after correcting that fixture, it failed on the absent discovery-evidence parameter. Implemented immutable discovery references, per-identity continuous interval extension, candidate revalidation and Generation retention references. Candidate/Generation group: 9 passed / 1.38 seconds (24380 exit 0). Covers missing baseline, interval gaps, absent scope, incomplete categories, independent pending cutoff and unchanged raw collection references.
- Daily refresh now preserves current and prior discovery receipts and queries all historical identities listed by the target (including delisted securities). The current candidate contract includes discovery references; no alternate format or migration. First combined integration run 20260912t215951z-49297-db08c096: 10 passed, 2 failed / 29.42 seconds (91308 exit 1, cleanup complete). Both failures were the old fixture assertion restricting announcement scope to the still-listed security. Updated that assertion and added evidence identity-scope/retention checks; targeted rerun 20260912t220139z-58693-df884cf8 is running as process 50533. Ruff and diff checks pass.
- Coverage acceptance is not complete: still require a multi-day rotating-collection Worker case, independent proof of discovery-announcement resolution when validating immutable candidates, and confirmation of receipt continuity through bootstrap and subsequent publication. These boundaries must be resolved before ticket review or completion.

- Corrected targeted discovery/target-guard rerun 20260912t220139z-58693-df884cf8: 2 tests, zero failures/errors; JUnit time 5.033 seconds. Historical discovery scope and retained receipt references pass. Ticket remains incomplete/uncommitted with the coverage boundaries above still open.

## Independent announcement resolution plan — 2026-09-13

- During candidate construction and revalidation, derive unresolved discovered report targets from the retained sparse indicator versions. Match security, report period and announcement date; require the latest observation state to be unambiguous and valid. Unknown report periods remain unresolved.
- Merge inferred unresolved dates with collection failures/pending instead of trusting the caller to list all targets. Revalidation rejects a manifest that removes or postpones an evidenced unresolved date. Read only target securities and evidence columns; do not expand daily financial series or introduce another persistent progress model.

- Independent-resolution red: 26617 exit 1, a discovered missing quarterly report produced empty unresolved_sources. Candidate build now derives earliest unresolved dates from discovery targets and the latest matching sparse observation state, merging them with explicit collection pending/failures. Validation repeats the derivation and rejects omitted or postponed unresolved targets. It reads only evidence columns for securities with discovered targets.
- Extended fixtures cover exact report/announcement matching, unknown report periods, latest same-event conflict, subsequent unambiguous observation, and a manifest with unresolved state removed. Final candidate/Generation/evidence/series group: 20 passed / 1.33 seconds (41179 exit 0); Ruff passes. Combined real Worker/pending/recovery validation running 20260912t220641z-61190-bb03df42 as process 72963. No compatibility paths or migrations added.

- Combined integration run 20260912t220641z-61190-bb03df42: 11 passed, 1 failed / 12.40 seconds (72963 exit 1, cleanup complete). Independent validation found the Aug 13 correction absent from indicator evidence, so coverage correctly ends Aug 13 instead of using only the later period-less pending target. Updated the overview expectation to ready_with_gaps and asserted the exact inferred date. A targeted rerun then exposed the corresponding family-level assertion (partial versus ready_with_pending): 20260912t220806z-62220-f068277a, 1 passed / 1 failed, 68464 exit 1. Both assertions now reflect the same evidence; rerun 20260912t220856z-62743-61f1756d is process 77105. These were stale readiness expectations, not relaxed coverage gates.

- Final targeted readiness/target-guard run 20260912t220856z-62743-61f1756d: 2 passed / 3.23 seconds, process 77105 exit 0 and cleanup complete. Independent unresolved-date, coverage cutoff, partial family/aggregate readiness and concurrent target protection pass. Candidate/Generation/evidence/series 20-test group and Ruff also pass. Ticket 05 remains incomplete/uncommitted: rotating multi-day collection and bootstrap continuity, broader consumer/resource acceptance, serial reviews and independent commit remain.

## Multi-day rotating publication acceptance plan — 2026-09-13

- Bootstrap the two historical securities through one target date, then run two further Financial Refresh publications with the existing bounded dispatcher set to one security per day in the test. Keep complete empty announcement discoveries for both historical identities.
- Assert only one security is rechecked each later day, the family remains usable through each target, at least one security's raw query watermark remains earlier, and every prior discovery receipt remains referenced. Reopen each published Generation and read the same indicator values without provider reads. Use the real daily service, database and mounted immutable store in the existing isolated integration runner.

- Multi-day publication run 20260912t221103z-63749-d228904d: 1 passed / 2.62 seconds, process 31100 exit 0 and isolated cleanup complete. After a complete two-security baseline, subsequent publications recheck one security per day, rotate across both, advance indicator coverage despite an older raw query watermark for the other security, preserve all prior discovery references, and read EPS through the published Generation without further source calls. Ruff passed.
- Remaining bootstrap boundary: before the first all-identity baseline exists, daily discovery receipts are written but not yet retained by a candidate. The next build currently gathers only its own receipt plus any prior candidate receipts; it does not accumulate discovery receipts from earlier pre-baseline operations. A bootstrap longer than the discovery overlap can therefore leave a proof gap. Preserve/query these receipts through an existing durable operation/evidence boundary and verify retention before claiming full coverage acceptance. Consumer/resource acceptance and serial ticket reviews also remain; 05 is incomplete/uncommitted.

## Bootstrap discovery continuity plan — 2026-09-13

- Existing daily-operation discovery JSON survives retention release and is not deleted by production code. Persist its actual historical identity scope at discovery time, then materialize missing immutable receipts from those durable records during candidate building. Reuse the existing JSON column and raw store; no schema/table/version change.
- Collect discovery operations through the target, starting at the previous candidate's coverage end when one exists. Preserve earlier candidate references. This includes pre-baseline operations without rereading source data or relying on unreferenced raw files surviving garbage collection.
- Extend the rotating integration acceptance with delayed bootstrap: one security succeeds only on the first date, the other only after two discovery windows. Intermediate operations are released. The final family must bridge the old source watermark using all retained discovery intervals.

- Delayed-bootstrap red 20260912t221409z-64984-efdb083b: 1 passed / 1 failed, 4.50 seconds, process 41753 exit 1. Final coverage remained Aug 14 instead of Sep 3 because pre-baseline discovery windows were omitted.
- Discovery operation JSON now persists its exact historical identity scope. Candidate preparation reconstructs immutable discovery receipts from retained operations through the target, bounded below by prior candidate coverage when available, and unions prior candidate references. Operation retention release preserves these JSON facts. No new schema column, table, compatibility path or migration.
- Corrected rotation/bootstrap run 20260912t221529z-65653-36632e57: 2 passed / 4.15 seconds, process 41926 exit 0 and cleanup complete. Delayed scenario releases both pre-baseline operations, then proves all three discovery receipts bridge the old raw watermark and permit Sep 3 coverage. Normal one-security-per-day rotation still passes. Ruff and diff checks passed.

- Expanded discovery-contract run 20260912t221633z-66277-b8215ab9: 19 passed, 3 failed / 15.74 seconds, 53122 exit 1 and cleanup complete. Failures were remaining current-listing-only source-scope expectations in unchanged-statement and zero-trigger fixtures. Updated those to include both historical securities; unchanged statements still reuse their tables and close their own trigger, while the unmatched indicator announcement correctly leaves one pending security.
- Final discovery-contract run 20260912t221751z-66941-260287f2: 22 tests, zero failures/errors, JUnit 16.039 seconds; process 8594 exit 0 and cleanup complete. Covers normal and delayed bootstrap, daily no-change/zero-trigger refresh, retained discovery state, atomic target recording, prior-gap resolution and direct/Worker successor recovery. Ruff and diff checks pass. Ticket 05 remains incomplete/uncommitted: broader consumer/resource acceptance, full affected checks and serial Standards/Spec reviews remain before independent commit.

## Consumer acceptance plan — 2026-09-13

- Verify the current catalog/DSL/dependency/HTTP-MCP contracts with the six indicator fields enabled. Existing source-only and historical Generations must still expose their own field subsets; add only missing public-boundary coverage.
- Then extend existing real ResearchRun/Batch/DailyTrack acceptance fixtures to consume a published indicator family, checking common frozen coordinates, source-free execution, null handling and actual field costs. Finish relevant UI/Agent catalog evidence before serial ticket reviews. Catalog counts alone do not prove consumer execution.

- Initial DSL/dependency/HTTP-MCP contract selection: 156 passed, 1 failed / 16.13 seconds (93349 exit 1); failure was the browser catalog fixture still containing 63 fields. Regenerated that fixture from the public catalog, added the six-field indicator family to the browser snapshot, and updated the explicit total to 69. A follow-up exposed the matching stale 63-count assertion; after fixing it, all 61 Alpha Language contract tests passed / 0.39 seconds (44200 exit 0). The other 96 previously passing tests were not redundantly rerun.
- Real browser component acceptance: 2 passed / 7.3 seconds (90677 exit 0), desktop 1280 and mobile 390 widths. Verifies the existing four Data sections, indicator source filter (six rows), Chinese q_roe search, indicator formula completion, and previous daily/basic/statement filters. This is browser component evidence, not a deployed live-site claim.
- Added indicator support to the existing immutable MCP acceptance fixture (51 securities, full 167-column source observations, qualified six-field candidate; no real supplier requests). Real MCP catalog -> submit rank(roe + q_roe + netprofit_yoy) -> isolated Research Worker -> successful retrievable result passes. Run 20260912t222243z-68652-084017e6: 1 test, no skips/failures/errors, JUnit 8.561 seconds; 32472 exit 0 and cleanup complete. Source units/field ownership checked through MCP.
- Ruff passes after formatting the fixture imports/long line. Web typecheck running as 60898. Batch/DailyTrack consumer equivalence, broader resource checks, required full affected checks and serial Standards/Spec reviews remain before ticket completion and independent commit.

- Web typecheck completed: 60898 exit 0. Diff whitespace check passes. Ticket 05 remains incomplete/uncommitted pending the remaining consumer/resource and serial review gates above.

## Batch and DailyTrack indicator acceptance plan — 2026-09-13

- Use the same retained 51-security indicator Generation for an ordinary strategy Run and a one-child strategy Batch with identical formula/range/protocol. Compare public strategy metrics and frozen data provenance after real separate Worker execution.
- Start DailyTrack from the completed Batch child through MCP, run the real Tracking Worker using existing explicit refresh/catch-up behavior, and assert preserved origin plus advancement to the frozen Head's final session. No supplier provider exists in these research execution fixtures.

- Indicator consumer run 20260912t222650z-70149-58ccb890: 1 passed / 15.20 seconds. A real ordinary Research Worker and Batch Worker execute the identical indicator formula/range/protocol against the same immutable 51-security Generation; public strategy metrics and data provenance match exactly. MCP starts a DailyTrack from the completed Batch child, and the real Tracking Worker catches up to the Head calendar end while preserving its origin. Fixtures contain saved source observations and provide no supplier implementation to the research path.
- Ruff passed for the added acceptance. Remaining 05 gates are broader resource bounds, full affected checks, explicit serial Standards/Spec review and fixes/re-review, final tracker acceptance and independent commit. Ticket remains incomplete; no 06 implementation started.

- Consumer acceptance process 39966 completed exit 0 and isolated cleanup completed.
- Full quick check `mise exec -- pnpm test`, process 3255 exit 1: Node tooling 29 passed and Ruff passed; Python 1342 passed / 3 failed / 132.49 seconds. Downstream quick-check stages did not run after Python failure. Failures: (1) Data imports outward adapters in new indicator modules, a real architectural violation requiring source-port inversion; (2) new candidate docstring ends with `publication.` and trips the existing cross-schema string-literal check; (3) empty-Head family count expects 3 instead of current 4. Do not relax the import-layer boundary or add compatibility to silence these. Fix the Data/adapter dependency direction, update the accurate current family expectation and clarify the docstring, then rerun affected checks and remaining quick stages.

## Indicator source dependency correction plan — 2026-09-13

- Data owns the retained indicator source contract, source port and bounded report-range/checkpoint orchestration. The TuShare adapter implements that port and normalizes vendor exceptions to DataSourceError. Entry points explicitly compose the adapter; Data never imports adapters, even for annotations.
- Update the current callers/tests to this single contract. Move rather than duplicate the 167-column definition and remove the old source class; do not add aliases, fallbacks or weaken the import graph test.
- Recheck architecture, source/checkpoint/candidate unit tests, then real refresh/recovery paths and outstanding quick-check stages. Also correct the empty-Head four-family expectation and wording falsely resembling a schema-qualified SQL reference.

- Source-port correction: Data now owns the 167-column source contract and bounded range collector; the external TuShare adapter normalizes vendor failures. Operator composition and integration fixtures explicitly wrap vendor providers. Architecture/source/checkpoint/family selection passed 45 tests in 3.01 seconds (10408 exit 0), before adding three adapter error cases. Ruff passes for the updated source and tests. Full quick check (97980) and isolated source-port/discovery/progress run (32554, 20260912t223819z-83007-b7e34627) are running; not yet counted as passed.

## Indicator read resource plan — 2026-09-13

- Inspection found the resolver accumulates one Python dictionary per requested stock/session before Arrow conversion. Replace this dense Python object intermediate with fixed numeric arrays for the requested fields and Arrow coordinate columns, following existing columnar readers. Keep sparse report selection, visibility and missing semantics unchanged; no persisted daily financial expansion.
- Verify requested-column projection and identical values/nulls across multiple instruments, sessions and fields through the public reader. Measure representative peak allocation against the former implementation before claiming resource improvement. Final returned data necessarily scales with requested coordinates and columns; do not claim constant total memory.

- Source-port/discovery/progress integration run 20260912t223819z-83007-b7e34627: 26 passed, 475 deselected in 49.41 seconds; process 32554 exit 0 and isolated cleanup completed. This rechecks normalized failures, pending/checkpoint recovery, normal/delayed bootstrap, discovery scope and publication recovery after the dependency inversion. No shared development or production data changed.

- Full quick check 97980 completed exit 0 before the columnar optimization: tooling 29 tests, Ruff, Python 1348 tests in 176.05 seconds, and downstream TypeScript/Agent/Web stages passed (Web 355 tests). One existing forkpty deprecation warning; no failed check.
- Replaced dense per-coordinate Python dictionaries in indicator resolve_table with requested-field float64 arrays and Arrow coordinate columns. Output remains sorted by session/instrument with unchanged null and unit semantics. Added public multi-instrument projection/missing test; series plus Generation tests passed 5 / 0.77 seconds (35226 exit 0), Ruff and diff whitespace checks pass.
- Bounded resource comparison: 100 securities × 500 sessions × 6 fields, same 50,000-row/3,850,000-byte Arrow output. tracemalloc Python peak decreased from 24,797,682 to 2,820,380 bytes. Timings under tracing were 3.012 and 3.780 seconds; this demonstrates lower Python intermediate allocation, not lower runtime or constant/process-wide memory. Measurement script and old implementation saved under /tmp for review; production reader retains sparse source facts and materializes only requested coordinates.
- Beginning serial Standards review of snapshot /tmp/issue05-review-source-port, current ticket changes relative to 5dc859f4; Spec review follows after Standards. No ticket completion or commit yet.

- Current ResearchRun admission derives field_count from compiled.field_ids_by_identifier and computes calculation coordinates including effective lookback; it does not charge the entire catalog. Existing chunk-planning tests cover field-dependent capacity. Multi-instrument reader test explicitly verifies only eps/roe plus visibility metadata are requested and unrelated stocks remain missing. Post-optimization real consumer recheck is running as 72614 (20260912t224432z-95457-c03d7a8c); not yet a pass.

- Post-optimization consumer run 20260912t224432z-95457-c03d7a8c passed 1 test in 18.86 seconds (72614 exit 0, cleanup complete): ordinary Run and Batch metrics/provenance match, DailyTrack advances with original origin retained.

## Standards R1 repair plan — 2026-09-13

- Review reports P1: composition can omit prior discovery receipts and erase known pending; require retained discovery evidence as well as retained source observations, so candidate validation must resolve all previously known announcements from actual evidence.
- Review reports P2: candidate accepts malformed/non-finite/float-overflow authoring values. Validate the six enabled fields during candidate projection using the same numeric conversion as research reading. Preserve raw receipts; reject invalid candidates before readiness/publication.
- Add regression cases first, observe rejection tests fail, then implement and rerun candidate/Generation/series checks before serial Standards re-review and Spec review. Review changes stay inside ticket 05.

- Standards R1 regressions both reproduced: malformed-authoring candidate test failed without raising (23403 exit 1); Generation composition dropping an unresolved discovery receipt also failed without raising (80419 exit 1).
- Fixed composition to require retaining previous discovery receipts. Candidate projection now validates every enabled source cell with the same normalizer as Series reads, rejecting malformed/non-finite/float-overflow values while retaining original observations. No alternate source, fallback or migration.
- Candidate/Generation/Series verification passed 14 tests in 2.76 seconds (23647 exit 0); Ruff passed. R2 snapshot /tmp/issue05-review-r2 captures these five changed files for Standards re-review, then Spec review.

- Post-review source/discovery/progress integration recheck running as 52706, run 20260912t224832z-98660-ef78b9b8. Standards R2 review is active; Spec review has not started. Ticket remains incomplete/uncommitted.

- Standards R2 completed: P1 and P2 closed; zero remaining actionable Standards findings. Reviewer inspected captured changes only, did not rerun tests. Serial Spec review now started against the same R2 snapshot; no implementation for 06 begun.

- R2 integration run 20260912t224832z-98660-ef78b9b8 completed with 24 passed / 2 failed in 21.22 seconds, 52706 exit 1 and cleanup complete. Both failures are successor-indicator recovery fixtures constructing a new candidate without copying retained discovery receipts, now correctly rejected by the R2 invariant. Updated the fixture to retain those receipts; production daily preparation already unions them. Recovery behavior assertions remain unchanged. Rerun the affected successor recovery cases.


## Final acceptance — 2026-09-13

- Criteria 1–3: qualified six-field catalog and retained 167-column source contract; bounded single-stock report-range splitting, cap rejection and historical identity tests. Live qualification artifacts record the two-company/2023–2025 source sample and independent statement comparisons; full-history qualification belongs to 07.
- Criteria 4–6: immutable observations, earliest observation preservation, announcement-aligned history, invalid announcement quarantine, later observed revisions and ambiguous-version missing behavior verified by evidence and Series tests. No invented revision/report metadata.
- Criteria 7–8: isolated collection/progress/discovery/recovery tests prove independent pending, retry/checkpoint recovery, raw-history and announcement continuity. Source error normalization is Data-owned at its port and implemented by the TuShare adapter; no research-time supplier calls.
- Criteria 9–10: sparse projected reads, unit conversion, null behavior, per-family admission, current catalog and four-section browser acceptance. Resource changes preserve columnar values; invalid enabled source numbers are rejected before publication, and retained discovery receipts cannot be dropped by composition.
- Criteria 11–12: real MCP Run acceptance, ordinary Run/Batch equality and DailyTrack advancement passed against frozen retained sources. Browser desktop/mobile checks, quick regression and affected integration checks passed. No production publication or push.
- Standards R1 findings P1/P2 fixed and R2 re-review closed both; Spec review reports zero actionable findings and includes the successor-fixture evidence-retention correction. Reviews were serial and static; tests separately executed by the primary task.
- Final recovery run 20260912t224958z-1547-3de96550: 4 passed in 15.09 seconds, process 30179 exit 0, cleanup complete. Corrects the two fixture failures from the preceding 24-pass/2-fail run. Final Ruff and whitespace check passed.
- All 12 acceptance criteria are satisfied. This tracker update accompanies the independent ticket commit `feat(data): add sparse financial indicator research fields`. Tickets 06–08 remain unimplemented; the full 226-field goal is not complete.
