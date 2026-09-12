# Alternative C: make validation from a Result the common task

Design only. This alternative deliberately introduces one task-focused Module, `research_validation`, rather than exposing a general cross-product experiment language or stretching Research Batch. Proposed names are new domain terms requiring glossary/ADR acceptance, not claims about current capability.

## Evidence and the chosen seam

- `CONTEXT.md:117-123`: Research Agent acts for the Researcher; create/read authority does not grant cancellation or tracking stop.
- `CONTEXT.md:155-169`: each ResearchRun is fixed; Research Batch shares one Research Period, Universe, neutralization, Data Generation.
- `CONTEXT.md:505-507` and `apps/core/src/thesistrace/benchmark/models.py:20`: Strategy Comparison already means the strategy versus fixed CSI300 Benchmark Snapshot. Do not reuse this name for cross-Run validation.
- `docs/adr/0154-use-a-mounted-current-dataset-head-and-temporary-data-generations.md:3`: old Generations are temporary and may be collected.
- `docs/adr/0190-freeze-data-generation-at-researchrun-admission.md:3`: pin at admission, not at browser/MCP read.
- `docs/adr/0216-share-bounded-batch-calculation-and-recover-complete-tasks.md:3`: Batch shares same-scope computation and retries only classified transient failures.
- `docs/adr/0220-expose-research-agent-access-through-a-native-core-mcp-adapter.md:3`: transport Adapter calls module Interfaces; no alternate research implementation or Operator authority.
- `docs/adr/0222-keep-research-agent-execution-stateless-and-resource-addressed.md:3`: caller-stable request identity, durable resources, bounded polling.
- `docs/adr/0099-make-one-immutable-result-bundle-the-research-run-truth.md:3`: immutable published Result; transient Alpha/Label/execution detail currently is not retained truth.
- `docs/adr/0104-continue-dailytrack-from-one-fixed-origin.md:3`: DailyTrack continues a fixed account, not date-window reexecution.
- `apps/core/src/thesistrace/research_batch/models.py:59-64,97-112`: public Batch common dates, Strategy Sweep item only H/R. Cross-start validation is not a compatible extra item field.
- `apps/core/src/thesistrace/research_agent/registry.py:438-459,598-610,627-638`: existing state/read-result separation and action annotations.
- `apps/core/src/thesistrace/research_run/models.py:638-676,710-731,774-786`: Result section Interface already exists, provenance contains authorable input and Generation/execution facts. Reuse it.

Place the external seam at a task completed by both callers: "take this Result's research definition and validate specified independent accounts." The implementation owns source resolution, normalized conditions, shared admission Generation, run identities, comparable evidence and error semantics. HTTP and MCP remain Adapters. The webpage must not construct an experiment manifest and infer differences separately from the Agent.

## Interface: default task is one source, one account, optionally a few explicit changes

```ts
type MoneyCny = string; // canonical positive decimal, public limits discovered in constraints

type ValidationIntent = {
  source_run_id: string; // owned, succeeded Factor Evaluation or Strategy Backtest
  // REQUIRED: no hidden switch to source Generation or silently selecting current data
  data_basis: "current_dataset_head";
  account: {
    initial_cash_cny: MoneyCny;
    market_access: SupportedMarketAccess;
    costs: SupportedCostScenario;
  };
  // Required only for Factor source; Strategy source inherits these unless explicitly replaced.
  portfolio?: { holdings_count: number; rebalance_every_sessions: number };
  // Absent = one case using source Research Period; one axis only in initial release.
  vary?:
    | { kind: "start_date"; values: ISODate[] }
    | { kind: "research_period"; values: { start_date: ISODate; end_date: ISODate }[] }
    | { kind: "costs"; values: SupportedCostScenario[] };
};

type PreparedValidation = {
  normalized: ValidationSpec; // explicit finite cases, copied source input, explicit source receipt
  observed_head: string;
  expected_context_fingerprint: string; // binds head, contracts, constraints, source input checksum
  checks: CheckFinding[];
  availability: { checked_at: ISOTime; history: KnownExtent; capacity: "estimate" };
  limitations: LimitationCode[];
};

type ValidationAdmission =
  | { outcome: "accepted"; validation_id: string; status: "queued"; replayed: boolean;
      retry_after_seconds: number }
  | { outcome: "rejected"; issues: AdmissionIssue[]; replayed: boolean };

interface ResearchValidation {
  prepare(actor: Researcher, intent: ValidationIntent): PreparedValidation;
  submit(actor: Researcher, command: {
    request_id: string;
    spec: ValidationSpec;
    expected_context_fingerprint: string;
  }): ValidationAdmission;
  get(actor: Researcher, validation_id: string): ValidationProgress;
  results(actor: Researcher, query: {
    validation_id: string; limit?: number; cursor?: string;
  }): ValidationRows;
}
```

MCP names: `prepare_research_validation`, `submit_research_validation`, `get_research_validation`, `get_research_validation_results`. Four narrow task entry points are intentional: first is a read-only preview, second creates work, third reports execution, fourth reads scientific observations. Do not combine them with an `action` switch under one tool to achieve nominal method-count reduction and ambiguous tool annotations.

No `run_until_good`, recommended-best-strategy flag, implicit parameter search, hidden Cartesian product, arbitrary source Generation selector, or generic method to mutate frozen conditions. Existing factor discovery, formula diagnosis, single research, same-period Batch, result sections, and DailyTrack remain useful; this Module is additive because a durable multi-period task actually has a different lifecycle contract.

### Typed common usage

```ts
const p = validation.prepare(actor, {
  source_run_id: "run_source_strategy",
  data_basis: "current_dataset_head",
  account: {
    initial_cash_cny: "100000.00",
    market_access: "mainland_all_supported_boards", // example advertised enum, not real permission proof
    costs: { kind: "current_schedule_plus_extra_bps", extra_bps_per_side: 10 }
  },
  vary: { kind: "start_date", values: ["2025-09-10", "2026-01-05", "2026-06-01"] }
});
// p explicitly shows three independent restarts, same current Head, fixed copied formula/H/R,
// each date range, same 100k initial cash and exact fee meaning; no compute accepted yet.
const accepted = validation.submit(actor, {
  request_id: "my-stable-validation-request",
  spec: p.normalized,
  expected_context_fingerprint: p.expected_context_fingerprint
});
// Poll status; then request bounded rows. Inspect one row through existing get_research_run_result.
```

For Factor source the caller supplies H/R explicitly. For Strategy source source H/R inherit. Baseline is not added implicitly: empty vary means one baseline; when vary is provided exactly those cases are accepted. Prepared case keys are derived deterministically from normalized values, labels remain presentation only. A source receipt stores original Run identity, input checksum, Result content identity, and generation/execution differences. Copy definition from the source, never treat source Result as fresh Alpha values.

## Exact semantics and authority

1. **Actor** is authenticated Researcher from verified session/token. Tools never accept researcher_id/owner as a user-controlled override. `prepare`/`get`/`results` require `research:read`; `submit` requires both `research:read` (uses source) and `research:execute`. Existing registry currently models one required_scope (`research_agent/registry.py:276-284`); introduce all-required scopes at the capability check seam or recheck conjunction in the Module, rather than pretending execute grants read. HTTP uses the same ownership validation. Source from another Researcher is not exposed (NOT_FOUND), with no leaked source metadata.
2. **Prepare is read-only.** It neither pins/reserves a Generation nor creates a draft/Run. It may parse formula, resolve public source facts, check dates/declared field readiness/history metadata and bounded resource estimates. It must not claim actual row coverage, complete solvency, runtime success, or measured memory usage unless these facts already exist. Observed Head is a checked fact, not a durable lease.
3. **Admission revalidates atomically.** The submitted normalized spec is untrusted input: resolve source and ownership again, verify copied source fields and allowed changes, and derive the fingerprint from authoritative facts; a caller-provided digest is not authorization. `expected_context_fingerprint` protects against changed Head/contracts/source; mismatch is structured `CONTEXT_CHANGED`, no work. Current Head is pinned for all accepted children once; all accepted exact inputs and source receipt are stored. Do not independently submit children while Head may change. This requires a real internal admission seam with caller-supplied already-retained scope, not reentering current public `admit` methods N times.
4. **Source-data truth.** Default task says explicitly `current_dataset_head`: "repeat this definition against current data," not reproduce historical execution. Original and new Generation difference appears in preview and result manifest, and original Result is not mixed in as same-data baseline. Source Result old Generation may be GCed; this does not block copying its authoritative definition if available. Exact historical-source reexecution is out of first release scope, not a best-effort feature. Any future explicit source-generation mode must fail SOURCE_DATA_UNAVAILABLE if retention absent, never silently current Head.
5. **Account semantics.** Cases are independent new accounts. One normalized initial capital/cost/access contract is frozen per child; details inherited by its Strategy Result and any resulting DailyTrack fixed origin. No first-pass optimization of fees, exposure or board access. User account-access choice expresses scenario, not brokerage verification.
6. **Durability.** Submit idempotency is Researcher plus request_id and canonical full spec. Replay returns same accepted/rejected outcome; changed payload conflicts. Accepted is not completed. Transport sessions and HTTP request IDs own no execution. Ordinary Run identities are returned and reused across reconnects. Child failures remain rows, never zero-return substitutes; validation status derives counts and terminal states, no partial Result Bundle is published for failed child.
7. **Cancellation.** Not implied by validation create/read. V1 can use existing `cancel_research_run` on each ordinary child with research:cancel (explicit selected identity, idempotency). A future group cancel is justified only with durable group cancellation intent and admission/execution race tests. No hidden cancellation on source deletion, page leave, Agent disconnect or user deactivation.
8. **Deletion.** Store membership + immutable accepted input receipt independently of source and child availability. Deletion does not erase historical question; corresponding row becomes result_deleted/unavailable, not repopulated from cache or silently rerun. Follow current Research Ownership throughout.

Errors: schema invalid => existing INVALID_INPUT; semantic issue => rejected issue with case_key/field/code; expected source kind/state => SOURCE_NOT_SUCCEEDED; unavailable source => NOT_FOUND; changed context => CONTEXT_CHANGED; invalid dates/history => INSUFFICIENT_HISTORY / PERIOD_OUTSIDE_COVERAGE; known quota => CAPACITY_REJECTED; transient dependency => TEMPORARILY_UNAVAILABLE/retryable; permanent resource exhaustion remains terminal without unchanged retries. Codes above new domain issues, not claim existing enums. All include bounded safe context, trace identity; no underlying storage keys or auth internals.

## Bounded evidence, not a second result authority

`get` reports accepted immutable conditions, source receipt identity, progress counts and child identities (bounded page if needed), no factor/NAV payload. `results` reads immutable completed Result sections and gives at most20 case rows first release: run_id, status, exact dates/session count/capital/costs, intentional changes, extra differences, net return, DD, Sharpe, fees, cash ratio, Result identity, section availability. It does not manufacture a winning recommendation or compare unlike horizons solely by total profit. The declared one-axis design makes attribution conditions simple to validate centrally.

Detailed factor diagnostics and ledger belong to the existing Result Module Interface (`get_research_run_result`), not new `explain_factor`, `explain_cash`, `get_best`, per-metric or per-rejection tools. HTTP consumes the same semantic sections and their units/reasons.

- Extend Factor section summary with quantile/tail declared diagnostic availability. New `factor_diagnostics` pages include horizon, selection N/group, signal session, observation counts, pairing/count semantics and exclusion reasons. Need separate count for each quantile and jointly valid q5−q1; valid-date means are not algebraically interchangeable. Tail label returns are not account returns.
- Add frozen `strategy_ledger` semantic page (session filter + opaque cursor, limit <=50), with accepted public financial account meaning. Do not expose recovery accumulators or object keys. Agent can drill one session; web can show identical rows. Parent should decide exact ledger row contract from kernel audit.
- Result currently has per-504-session 1MiB byte budget: `research_run/result.py:60-68,128-155`; ledger can greatly exceed it. Must design measured bounded admission/storage budgeting and partitioned publication, not simply append all instrument rows into existing JSON. Publication verifies counts/order/finiteness and complete accepted diagnostics before successful Result.
- Factor durable schema currently stores only summary (`result_schema.py:25-78`), Strategy daily observations only10 public fields (`result.py:87-106`, `result_schema.py:159-169`). No current read can reconstruct missing historical source records/holdings or claim posthoc diagnostic completeness.

## Immutable Result evolution

New diagnostics must be calculated during new research and published into its immutable Result contract; reading old Result cannot trigger calculation, attach newly inferred facts, change original digest or upgrade old financial semantics. An explicit migration may preserve old content and record current-envelope section availability as `not_recorded_at_execution`, with original calculation identity retained. It must not fill zero or reinterpret earlier values. Exact migration/archive shape requires publication/retention design and rollback proof; do not add runtime old-version compatibility branches as a shortcut. A genuinely missing diagnostic needs a new Run, visibly using current Head unless exact retained source-mode is explicitly supported. ADR0099's exclusion of transient detail needs an explicit narrow revision to permit selected ledger facts as retained Result evidence; avoid retaining every execution intermediate.

## Frontend shape and same observation guarantee

- `apps/web/src/research-runs/ResearchRunsPage.tsx:1437-1499`: result page already owns Factor summary and Strategy sections; add source action "验证账户" and render quantile/tail rows from shared section DTO, not browser-side recomputation. `FactorHorizonView` currently only correlations/coverage despite quantiles being typed at30-42.
- Source action opens small intent panel: account, H/R if factor source, optional one compare axis. Calls prepare, shows exact cases and current/source data difference, then submit. Browser Draft remains unsubmitted authoring, not accepted Validation.
- Validation detail is one progress/case table with links to existing Run detail. `StrategyComparisonPanel.tsx:1-26` stays CSI300; use separate "验证条件对照" heading/view rather than overload benchmark chart.
- Existing ResearchWorkspacePage H/R form (`:600-652`) uses shared authoring constraints. Extend `research_authoring/models.py:29-40` and `service.py:29-61` for actual validated account/diagnostic ranges; do not hardcode supported choices independently in browser and Agent descriptions.

## Hidden implementation / dependencies / depth

Same-process research modules and kernel have inspectable source; deepen internal admission/result seams where scope/account actually varies. Data Head retention, publication and persistence are cross-seam dependencies with real current Adapters; use existing bindings, avoid a novel generic storage protocol for this task. HTTP and MCP are two real caller Adapters. Clock/transaction scope can be injected at current composition seam; no HTTP calls from one domain Module back to itself. The validation Module owns normalized case expansion, source receipts, atomic admission and comparability. Kernel owns accounting and diagnostics. Publication owns immutable complete evidence. Neither Adapter calculates trade results.

Deletion test: deleting the validation Module would force both UI and Agent clients to expand source inheritance, detect changed Head, coordinate all-or-none admission, track child failures and compare provenance themselves. That complexity is real, so the Module earns depth. Deleting an added `explain_factor` wrapper would remove almost no complexity beyond a result-section alias: shallow, omit.

Tradeoffs: excellent default path and visible constraints; more new durable state/ownership/deletion work than simply adding a pure multi-Run read. One-axis cases intentionally omit arbitrary matrices and mixed-factor experiments. Four new tools add surface, but preserve honest action/read separation; a generalized prepare/submit/get-everything tool would look smaller while requiring callers to learn a larger implicit protocol. If scope/budget cannot support durable validation now, first ship account + diagnostics + explicit existing single Runs and a read-only multi-Run view, but call it a staged delivery rather than claiming atomic cross-date Validation exists.

## Verification surface (proposal only, not tests run)

Through shared Interface: source authority conjunction; source missing/GCed distinction; preview has no pins/writes; Head changes before admission rejects; concurrent refresh after admission preserves common Generation; idempotent request replay/conflict; every accepted case becomes exactly one ordinary Run; failed/deleted cases stay visible; terminal Result-only diagnostics; read-only does not schedule; section pagination bound/ownership/result binding; money/ledger reconciliation; web and MCP exact DTO parity; explicit migration backup/rollback/hash preservation. Scripted/Fake Agent proves engineering flow without browser; separate fixed real-agent evaluations measure whether common task uses few calls and correctly identifies changed-data/noncomparable results.
