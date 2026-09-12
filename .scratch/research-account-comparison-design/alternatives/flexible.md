# Option B: finite owned Research Comparison Module

Design only. Based on current source inspected on 2026-09-11. No implementation, tests, or deployment performed.

## Recommendation and depth

Add a researcher-owned `research_comparison` Module. Define **Research Comparison** in CONTEXT as a finite, immutable protocol relating independently admitted ResearchRuns and declaring intended differences. Do not call it `Strategy Comparison`: that domain term already means comparison against the CSI 300 Benchmark. Do not broaden Research Batch's shared Research Period invariant implicitly.

The Module earns depth by owning one frozen protocol, source resolution, admissible case expansion, atomic multi-Run admission, persistent case identity, comparison semantics, idempotency and deletion-aware lineage. It must not become a facade that calls submit_run N times: deleting this Module should push all those responsibilities back into HTTP and MCP callers. The HTTP and native MCP Adapters both cross this same Interface; they do not implement experiment expansion or numeric interpretation.

Smallest execution implementation: all cases are ordinary ResearchRuns handled by the existing Research Worker. A Research Comparison is an admission/read authority, not a new worker, attempt, checkpoint, or result authority. Results remain one immutable Result Bundle per successful Run. The Module reports a bounded read projection of those Results, never a mutable replacement Result.

## Public Interface

```python
class ResearchComparisons:
    def inspect(self, researcher, proposal: ComparisonProposal) -> Inspection: ...
    def admit(self, researcher, command: AdmitComparison) -> AdmissionOutcome: ...
    def get(self, researcher, comparison_id, section='summary', cursor=None,
            limit=20) -> ComparisonView: ...
    def list(self, researcher, cursor=None, limit=20) -> ComparisonList: ...
```

There are four entry points because this option optimizes finite flexibility, not minimum method count. `inspect` and `admit` use exactly the same normalization and admission validation; inspection creates no Run, reservation, pin, or durable comparison. Mutation uses existing caller-stable request identity. `get` is a bounded read: section `summary|cases|comparison`; individual curves/diagnostic facts use existing Run result sections.

First-version proposal:

```json
{
  "source": {"kind":"strategy_result", "run_id":"run_source"},
  "data_policy":"current",
  "mode":"independent_restart",
  "vary":["start_date","initial_cash_cny","extra_cost_bps"],
  "cases":[
    {"case_key":"base","start_date":"2025-09-10","initial_cash_cny":"100000.00","extra_cost_bps":0},
    {"case_key":"later","start_date":"2026-01-05","initial_cash_cny":"100000.00","extra_cost_bps":0},
    {"case_key":"cost10","start_date":"2025-09-10","initial_cash_cny":"100000.00","extra_cost_bps":10}
  ]
}
```

Admit adds `request_id` and an optional `expected_current_generation_id` concurrency assertion obtained from inspect. That assertion is not a historical generation selector. First version requires 2–20 explicit cases, unique case keys, no implicit Cartesian product, no generic expression patches. Supported varying fields are a finite allowlist; fixed fields are inherited once from an authorized successful source Result. Start/end dates, Initial Cash, Holdings Count, Rebalance Interval, and supported cost scenario may vary as implemented. Source formula/Universe/neutralization are fixed; changing Alpha requires another comparison protocol, not a hidden case override. Input uses decimal money with explicit current cost semantics, not a label whose meaning can be edited later.

Later a discriminated `source.kind='explicit_strategy'` can accept one full strategy specification for Agent-initiated work without a source Result. Add it only when requested; do not initially support arbitrary strategy lists or mixed factor/strategy graphs. Creating a factor-derived strategy is a ResearchRun admission capability with real source lineage, then comparison can start from the resulting strategy. Factor TopN diagnostics remain ResearchRun/Research Kernel responsibility.

`vary` declares attribution, not a scientific causal guarantee. Expansion rejects undeclared varying inputs and reports duplicate case computations as validation issues rather than silently merging them. Multiple deliberate axes are allowed, but returned warnings explain when one-axis attribution is unavailable. Do not rank by cumulative return across unequal lengths automatically.

## What Agent gets

Inspection returns resolved fixed inputs, all normalized cases, current data-through date/generation, source-generation difference, per-case Research Period/session count/first investable Entry Open, required warm-up, available history, field readiness, total accepted-run quota requirement, per-case execution estimates and error codes. The plan estimate explicitly says whether execution is ordinary or shared; no hidden synchronous backtest and no promise of queue reservation.

Admission returns accepted/rejected, replayed, comparison_id, frozen protocol digest, current-generation facts and all case_key→run_id bindings in submitted order. Rejected cases include field and case_key. All accepted cases exist atomically before return; accepted does not mean computed.

Read summary returns completion counts, `pending|running|terminal`, finished outcomes, result availability, and bounded poll hint. Avoid a new durable status state machine: derive it transactionally from case Runs plus deletion tombstones. A failed item does not become missing evidence or investment failure. Read comparison rows contain actual frozen conditions, Result identity/content digest, declared deltas, unexpected differences, calculation contracts, metrics, period length, costs/cash and missing reasons. Use existing authoritative metrics; no read-time whole-backtest execution. Include `comparison_basis='independent_restart'`. `continuous_window` must be a later separately governed read operation with its own interval-metric semantics; `walk_forward` is out of this scope.

## Atomic admission and Data Generation seam

Current code already provides useful internal seams:

- `research_run/service.py:911` compiles/prepares a child against an injected DatasetAdmissionSnapshot.
- `research_run/service.py:950` admits that prepared child inside a caller transaction, with execution owner and Generation retention choice.
- `research_batch/service.py:692` prepares a bounded list once against a shared snapshot, then `:774` onward admits all items in one transaction; `:846` invokes child admission.
- `data/lifecycle.py:106` reads current admission while holding the lifecycle fence; `:221` retains the selected Generation transactionally.

Proposed transaction sequence:

1. Normalize proposal and hash all meaningful explicit inputs (not generated IDs). Check researcher/request receipt first. Resolve source ownership, source Result manifest/input and source availability using a bounded ResearchRun Interface.
2. Read one current admission snapshot; prepare all children outside the write transaction. Source historical Generation is provenance only, never selected for new execution. Computation is bounded by ≤20 cases and formula limits.
3. Start the short write transaction. Lock request identity; recheck replay/conflict. Reauthorize source/folder under locks; enforce an admission quota lock shared with ordinary and Batch admission so simultaneous requests cannot each pass count independently.
4. Acquire lifecycle fence in documented lock order and compare current manifest with the prepared snapshot. If moved, reject `DATA_HEAD_CHANGED` with the new context; do not silently mix generations or rerun part of the list. `expected_current_generation_id`, if present, also must match. The predicate is for optimistic concurrency, not public historical selection.
5. Insert comparison protocol/items and call child admission for every Run with `execution_owner='ordinary'`, `retain_generation=True`. Every child gets its own ordinary execution plan and retention. Insert comparison request receipt. Commit once. Any invalid child/quota/Generation/SQL failure rolls back all comparison rows and children.
6. The existing ordinary worker picks up children after commit. No dispatch network call sits between durable creation and queueing.

Do not let the new Module write `research_runs.*` tables directly. Move any missing bounded authorize/read/commit operations into ResearchRun's current Interface. Introduce the all-count quota reservation under the existing ResearchRun authority, not a second quota implementation. Lock ordering must be tested against Refresh, source deletion, other admissions and publication maintenance. Current preparatory snapshot→commit gap must be handled explicitly, rather than claiming the existing batch code magically makes current selection atomic.

## Crash, retry and lifecycle

A crash before commit leaves no accepted work. A crash after commit before HTTP/MCP response is recovered by replaying identical request_id; changed payload conflicts. The receipt preserves original comparison and case IDs, including deleted cases, so transport replay cannot create replacement Runs. Durable rejected admission replays as rejected; a changed/retried proposal gets a new request identity.

Ordinary children retain existing attempt fencing, transient failure classification, lease and generation-pin behavior. Comparison never requeues terminal failed Runs from reads. A user-requested rerun is a new explicit comparison/Run on current data with lineage; execution-level transient retry preserves accepted input and Generation. No resource-limit retries that alter universe, history, or account inputs.

Do not add cancellation fan-out casually. First version uses existing explicit Run cancellation controls; comparison reads reflect them. If group cancel is required, add one explicit idempotent operation with a durable cancellation intent and reconciliation under existing worker authorities; a loop of best-effort calls is not atomic group cancellation. Group deletion first version deletes only comparison organization metadata (terminal comparison), never cascades ResearchRun or DailyTrack deletion.

A terminal Run may be deleted per current domain semantics. Preserve case_key, submitted ordinal, accepted input/protocol digest, final outcome, deleted_at and former run identity as a tombstone; result availability becomes deleted. Do not secretly pin the Result forever because a comparison mentions it, and do not duplicate all metrics to keep a deleted Result alive under another name. Successful Results remain ordinary Run truth; tombstones are admission/lifecycle history. Source lineage preserves source ID/content digest and copied accepted authoring inputs after source deletion, marks source availability explicitly, and does not retain the old Generation. A new comparison cannot resolve an already deleted source as if it were available.

## Finite flexibility and later sharing

All-ordinary execution is honest but can repeat costly preparation/Alpha work. It nevertheless fully delivers independent-start and capital/cost comparison with current worker recovery. First version should publicly expose actual plan summary `ordinary_runs: N, shared_alpha_factor_groups: 0`.

A measured second phase may partition the already normalized cases by exact same Generation, Research Period, Alpha, Universe, neutralization and diagnostic contract. Only compatible same-period groups can become existing Strategy Sweep Batch work; differing periods remain ordinary. Freeze each case's owner exactly once at admission. One case must never be simultaneously claimed by ordinary Research Worker and Batch Research Worker.

This needs a real Batch preparation/commit Interface that accepts the caller transaction and an already prepared group, without recursively calling public `admit_with_outcome` (which owns its own transaction). Comparison commits its protocol, bounded internal Batch groups, ordinary children, all case links and retentions in a single transaction. Existing Batch worker still owns shared Alpha-and-Factor task recovery and item execution; Comparison owns only grouping/comparability. The composition belongs in runtime wiring. Do not create a third execution worker or generic task DAG. Group/ordinary ownership and private artifact retention are internal plan facts, not a user-authored execution language.

Optimization is worth doing only after account sweep costs are measured. Adding this partitioning in the first release would change Batch authority, mixed queue admission and cancellation together, raising verification cost considerably. An alternative first release can support comparisons entirely by same-period Batch groups, but creates Batch records even for singleton date cases and couples organization to shared execution; all-ordinary first is the cleaner minimum.

## Data retention and upgrades

Queued children retain current Generation individually, attempt pins take over, terminal execution releases them using existing lifecycle behavior. Comparison stores Generation identity as evidence and does not create a permanent raw-data retention root. Historical Generation may be collected after durable retentions and active pins end. Results stay inspectable without source data; re-execution uses current admitted data and reports the changed source context.

Schema additions use an explicit versioned migration with pre-migration backup, exact from/to schema validation, execution record, rollback/repeat checks and data preservation. If Initial Cash becomes an immutable-input field, upgrading existing input records can explicitly materialize the historically fixed 10,000,000 value. Immutable Result bytes must not be edited in place. Any durable result-format change requires an explicitly designed immutable replacement/publication migration or an explicit absent-diagnostics status; do not synthesize uncomputed historic TopN statistics, reinterpret old semantics, or insert runtime multi-version fallbacks. Parent account/result design must settle this before implementation.

## Dependencies and verification

Preparation, case normalization, delta classification and factor/strategy metric projection are in-process dependencies. PostgreSQL and mounted datasets/publication are local dependencies tested with repository real PostgreSQL/RustFS isolation, not fake transactions. Quota identity from owned Auth is an existing remote-owned dependency using the current quota seam, without introducing a second research orchestration transport. Research HTTP and MCP are real Adapters at the same external Interface. Existing DatasetLifecycle/ResearchRun/Publication are real internal Module seams with actual reusable implementations; avoid speculative repository/engine protocol wrappers.

Meaningful verification through Interface:

- Same normalized HTTP and MCP command gives identical frozen case inputs and semantic results; pure MCP can submit, reconnect, replay, poll and read comparisons.
- Refresh racing admit gives all one Generation or complete structured rejection; quota overflow mid-list rolls back every child.
- Concurrent duplicate admission yields one comparison and one set of Runs; source deletion race is rejected or resolved before deletion with preserved frozen lineage.
- Worker death after admission, during child calculation and after publication retains canonical child identity/results without double execution authority.
- Independent restart actually starts at configured cash and each start date; no reuse of previous portfolio, no substitution of a NAV slice.
- Ordinary versus later optimized Batch execution on identical children is canonically exact; complete task recovery and release of private artifacts are checked at the existing Batch Interface.
- Run deletion preserves tombstone, source deletion preserves declared provenance, no unauthorized cross-researcher source/result reads, pagination binds researcher/comparison/protocol and immutable Result identifiers.

Read bounds: max20 cases per comparison, summary/cases one bounded query through ResearchRun-owned projection, no per-row giant Result downloads. Publish compact selected metrics/provenance once per Run or read only bounded semantic sections; observation curves remain separately paginated. Result digest-bound cursors prevent mixing immutable Results, while live status pages explicitly disclose observation time. Do not label all rows a frozen result until terminal; protocol is immutable while lifecycle progresses.

## Critique of prior tentative proposal

1. `strategy_comparison` Batch kind collides with existing benchmark vocabulary and violates shared-period invariant encoded in Batch model and capacity checks.
2. `preflight` cannot both freeze future research and remain unreserved/stateless. Return an observation plus expected-current assertion; true freeze is atomic admission.
3. `data_policy` must not expose historical Generation selection. Existing ADR0154 says historical Generations are temporary, and source Result does not guarantee replayable source data.
4. `compare_research_runs` as an arbitrary read helper is useful but does not itself own multi-Run request consistency, lifecycle or declared protocol; expanding it into a hidden submit/recompute operation would obscure authority.
5. Independent restart, existing-account slices and walk-forward are different computations. First comparison mode is independent_restart only.
6. Full ledger is a separate intentional publication-retention change (ADR0099), not just another MCP section name.

## Grounded anchors

- `CONTEXT.md:158` Research Batch shared period definition; `CONTEXT.md:505` Strategy Comparison is benchmark term.
- `docs/adr/0151-keep-research-authority-inside-a-module-first-core.md:3`: Module-first authority.
- `docs/adr/0190-freeze-data-generation-at-researchrun-admission.md:3`: freeze at admission.
- `docs/adr/0154-use-a-mounted-current-dataset-head-and-temporary-data-generations.md:3`: temporary historical Generations.
- `docs/adr/0216-share-bounded-batch-calculation-and-recover-complete-tasks.md:3`: Batch sharing/recovery.
- `docs/adr/0220-expose-research-agent-access-through-a-native-core-mcp-adapter.md:3`: same Module Interface through MCP.
- `docs/adr/0222-keep-research-agent-execution-stateless-and-resource-addressed.md:3`: request identity/resources, not transport sessions.
- `docs/adr/0099-make-one-immutable-result-bundle-the-research-run-truth.md:3`: complete immutable Result; transient detail not retained.
- `docs/adr/0104-continue-dailytrack-from-one-fixed-origin.md:3`: fixed tracking inception.
- `docs/adr/0108-require-canonical-exact-batch-incremental-equivalence.md:3`: exact calculation preservation.
- `apps/core/src/thesistrace/research_batch/models.py:37`: two current kinds; `:50` max20; `:56` shared dates; `:100` only holdings/rebalance per sweep item.
- `apps/core/src/thesistrace/research_batch/planning.py:73`: shared scope assertion.
- `apps/core/src/thesistrace/research_run/service.py:911`: preparation; `:950` transactional child admission; `:1088` receipt and ordinary admission; `:1680` terminal deletion/history; `:2583` worker claims only ordinary.
- `apps/core/src/thesistrace/research_run/schema.sql:83`: current execution owner restriction.
- `apps/core/src/thesistrace/research_batch/service.py:692`: all-child preparation/atomic commit; `:117` deletion tombstone hook; `:343` existing execution authority.
- `apps/core/src/thesistrace/data/lifecycle.py:106`: fenced current admission; `:221` retention; `:652` collection roots.
- `apps/core/src/thesistrace/publication/service.py:154`: publication mutation lock before product-row locks; `:340` record; `:570` manifest release.
- `apps/core/src/thesistrace/entrypoints/runtime.py:263`: ResearchRun dependency wiring; `:281` Batch wiring.
- `apps/core/src/thesistrace/research_agent/registry.py:265`: registry Module collection; `:896` semantic Run results forwarded through existing Interface.
- `apps/core/src/thesistrace/research_run/result_schema.py:32`: quantile scalar values; `:47` coverage lacks per-quantile counts.
