# Research Batch Worker

**Status:** ready-for-agent

## Problem Statement

A researcher currently has to submit several ResearchRuns one at a time when
evaluating multiple Alphas or scanning several parameter combinations for one
Strategy. Those Runs repeatedly prepare the same Data, Liquidity Universe, and
Forward Return Labels. A Strategy parameter sweep also recalculates the same
Alpha and Factor Evaluation for every parameter combination. This wastes
calculation time and I/O without improving the resulting research evidence.

Long sweeps also compete with interactive ordinary ResearchRuns when they use
the same Worker pool. A loop around the existing ResearchRun endpoint does not
solve either problem: it cannot share calculation, cannot expose one aggregate
lifecycle, and cannot recover or cancel the submitted set as one durable unit.

The researcher needs one backend-only Batch submission contract for independent
Factor Evaluations and single-Alpha Strategy sweeps. It must make the shared
work happen once, preserve an ordinary immutable ResearchRun and Result Bundle
for every submitted item, isolate Batch scheduling from ordinary Research, and
remain safe under rejection, retry, Worker loss, cancellation, publication
failure, deletion, and concurrent Data Refresh.

## Solution

Add Research Batch as a durable orchestration resource with two explicit
Research Batch Kinds:

1. `factor_evaluation` accepts an ordered list of independent Alpha inputs. It
   prepares the common Data, Liquidity Universe, and Forward Return Labels once,
   then executes one independent Alpha and Factor Evaluation per item.
2. `strategy_sweep` accepts exactly one Alpha and an ordered list of parameter
   combinations for the one current Strategy. It prepares Data and computes the
   shared Alpha and Factor once, then executes the Strategy once per parameter
   combination.

Admission atomically creates the Research Batch and one ordinary immutable
ResearchRun per submitted item, all pinned to the same Data Generation and
shared Research scope. Each Run owns its normal Result Bundle; the Batch owns
only membership, ordering, aggregate lifecycle, progress, retries,
cancellation, and the private shared artifact needed to recover a Strategy
Sweep. Equivalent Batch and individually admitted Runs must publish exactly
identical calculation Results under the existing semantic-result checksum;
each Result provenance still binds to its own ResearchRun identity.

Batch execution uses a dedicated single-slot `batch-research` Worker role from
the same Production Image, executable, Research Kernel, and Publication system
as ordinary Research. Ordinary Research, Batch Research, and Tracking remain
separate durable claim sets. One Batch Worker claims one complete Batch and
processes its items sequentially; additional replicas process different
Batches.

V1 is backend-only. Batch-owned Runs are initially organized in the stable
Batch Research Folder and remain visible through the existing Research list and
detail surfaces. The Batch API exposes admission, list, detail, and whole-Batch
cancellation, including durable completed-task progress and live progress for
the current incomplete task.

## User Stories

1. As a quantitative researcher, I want to submit several Alpha Formulas in one Factor Evaluation Batch, so that I do not have to create each ResearchRun manually.
2. As a quantitative researcher, I want to submit several Strategy parameter combinations for one Alpha, so that I can run a deliberate parameter sweep.
3. As a quantitative researcher, I want every Factor Batch item to produce an ordinary Factor Evaluation ResearchRun, so that I can inspect each result through the existing Research experience.
4. As a quantitative researcher, I want every Strategy Sweep item to produce an ordinary Strategy Backtest ResearchRun, so that every parameter combination has an independent immutable result.
5. As a quantitative researcher, I want Batch Results to equal separately admitted ResearchRun Results exactly, so that faster execution does not change the research answer.
6. As a quantitative researcher, I want one Batch to freeze one Research Period, Liquidity Universe, Industry Neutralization choice, Numeric Execution Contract, and Data Generation, so that its items are comparable.
7. As a quantitative researcher, I want Batch-owned Runs to receive stable IDs at admission, so that I can refer to them before execution finishes.
8. As a quantitative researcher, I want submitted item order preserved, so that results and failures map deterministically to my request.
9. As a quantitative researcher, I want to supply a unique `item_key` for every item, so that Batch diagnostics and results map back to my input without relying on display names.
10. As a quantitative researcher, I want Research Name to remain optional and mutable, so that display organization does not change calculation identity.
11. As a quantitative researcher, I want each Batch to accept at most twenty submitted items, so that one request remains operationally bounded.
12. As a quantitative researcher, I want a Factor Batch's twenty-item limit to apply to its `factors`, so that the limit is easy to understand.
13. As a quantitative researcher, I want a Strategy Sweep's twenty-item limit to apply to its `strategies` without counting the shared Alpha, so that I can scan twenty parameter combinations.
14. As a quantitative researcher, I want a request with no items or more than twenty items rejected before creation, so that malformed or oversized Batches leave no partial history.
15. As a quantitative researcher, I want every Alpha compiled and every item validated before admission commits, so that one bad item cannot leave a partial Batch.
16. As a quantitative researcher, I want admission to be all-or-nothing, so that the Batch and all child Runs either exist together or do not exist.
17. As an API client, I want admission request IDs to be idempotent, so that retrying an uncertain HTTP response cannot create duplicate Batches.
18. As an API client, I want reuse of one request ID with different input rejected as a conflict, so that an idempotency key cannot silently change meaning.
19. As an API client, I want validation issues to identify the item and field that failed, so that I can correct one large request efficiently.
20. As an API client, I want duplicate Factor computations rejected with both conflicting `item_key` values, so that equivalent formulas are not executed twice accidentally.
21. As an API client, I want formulas with different formatting but the same compiled Alpha Expression treated as duplicate Factor computations, so that names and whitespace cannot bypass duplicate detection.
22. As an API client, I want duplicate Strategy parameter tuples rejected with both conflicting `item_key` values, so that an identical portfolio configuration is not run twice accidentally.
23. As a quantitative researcher, I want different Alpha Factor Evaluations to share common Data, Universe, and Label preparation, so that repeated preparation work is eliminated.
24. As a quantitative researcher, I want each Factor Batch Alpha and Factor calculation to remain independent, so that different Alphas are never blended or inferred as one model.
25. As a quantitative researcher, I want a Strategy Sweep to calculate its Alpha and Factor exactly once, so that changing only Strategy parameters does not repeat upstream work.
26. As a quantitative researcher, I want the current Strategy calculation to run once per submitted parameter combination, so that every intended portfolio path receives its own result.
27. As a quantitative researcher, I want the Strategy Sweep's shared Factor result included in every child Strategy Backtest Result, so that each ordinary Run remains self-contained.
28. As a quantitative researcher, I want no implicit Alpha-by-Strategy cross-product, so that the server never creates computations I did not enumerate.
29. As a quantitative researcher, I want Batch work isolated from ordinary Research work, so that a long sweep cannot occupy an interactive Research Worker.
30. As an operator, I want ordinary Research Workers to ignore Batch-owned Runs, so that the shared Batch execution plan cannot be fragmented accidentally.
31. As an operator, I want Batch Research Workers to claim only Research Batches, so that Worker roles remain predictable.
32. As an operator, I want the oldest claimable Batch started first, so that Batch scheduling is FIFO without introducing priority policy.
33. As an operator, I want multiple Batch Worker replicas to claim different Batches, so that Batch throughput can scale without splitting one Batch.
34. As an operator, I want FIFO to govern claim order rather than completion order, so that a short later Batch may finish naturally on another replica.
35. As a quantitative researcher, I want one Batch Worker to process my Batch items in request order, so that execution and failure evidence remain deterministic.
36. As an operator, I want one Research Batch Attempt to own one supervised execution child, so that process loss and authority boundaries are unambiguous.
37. As an operator, I want the execution child to have no PostgreSQL or RustFS publication authority, so that a stale child cannot commit Product State.
38. As an operator, I want the supervisor to own claims, leases, fences, Data Generation protection, task acknowledgement, and publication, so that recovery has one authority.
39. As a quantitative researcher, I want completed Factor or Strategy tasks acknowledged durably, so that a later Attempt does not recompute completed work.
40. As a quantitative researcher, I want an interrupted incomplete Alpha-and-Factor or Strategy task restarted as a whole, so that recovery never combines unchecked partial calculation.
41. As an operator, I want internal calculation Chunks to remain bounded implementation details, so that memory control does not become a public Batch checkpoint contract.
42. As a quantitative researcher, I want transient infrastructure failures retried at most three total task attempts, so that recovery is useful but bounded.
43. As a quantitative researcher, I want deterministic input and calculation failures not retried, so that permanent errors fail promptly.
44. As a quantitative researcher, I want retry exhaustion scoped to the affected task and its dependants, so that independent later work can continue.
45. As a quantitative researcher, I want one permanent Factor item failure to leave other Factor items runnable, so that independent evaluations are isolated.
46. As a quantitative researcher, I want failure of the Strategy Sweep's shared Alpha-and-Factor task to fail all dependent Strategy Runs, so that no Strategy runs without its required signal.
47. As a quantitative researcher, I want failure of one Strategy parameter combination to affect only its own Run, so that other combinations can still succeed.
48. As a quantitative researcher, I want aggregate state to distinguish complete success, mixed success and failure, total failure, and explicit cancellation, so that Batch outcome is not ambiguous.
49. As an API client, I want durable progress to report completed whole tasks, so that I know what will survive Worker loss.
50. As an API client, I want live progress to report the current `item_key`, phase, Research Sessions, estimated percentage, elapsed time, and Attempt, so that I can display useful in-process progress.
51. As an API client, I want live progress identified as an estimate, so that it is not mistaken for committed output or a guaranteed finish time.
52. As an API client, I want an incomplete task's live progress allowed to reset after retry while completed-task counts remain unchanged, so that recovery is reported honestly.
53. As a quantitative researcher, I want to cancel the complete Batch with one idempotent request, so that I can stop work I no longer need.
54. As a quantitative researcher, I want queued cancellation to prevent any Batch execution, so that no Worker starts cancelled work.
55. As a quantitative researcher, I want running cancellation to fence publication immediately, so that stale work cannot win after my request.
56. As an operator, I want a running child given up to five seconds to stop cooperatively and then terminated if necessary, so that cancellation is prompt and confirmed.
57. As a quantitative researcher, I want already completed Results preserved when I cancel a Batch, so that cancellation does not become destructive rollback.
58. As a quantitative researcher, I want every unfinished Run marked cancelled after Batch cancellation, so that no item remains indefinitely queued or running.
59. As an operator, I want incomplete Checkpoints, live heartbeat, unchecked output, Attempt files, and now-unused shared artifacts cleaned after cancellation, so that cancelled work retains no resumable calculation state.
60. As a quantitative researcher, I want a cancelled Batch to require new admission for any unfinished inputs, so that cancellation remains terminal.
61. As a quantitative researcher, I want successful Strategy child Runs to retain the ordinary ability to seed a DailyTrack, so that Batch submission does not reduce product capability.
62. As a quantitative researcher, I want Batch-owned Runs initially organized in the Batch Research Folder, so that generated research is easy to find without a Batch frontend.
63. As a quantitative researcher, I want to rename or move a Batch-owned Run normally, so that Folder organization remains independent of immutable Batch membership.
64. As a quantitative researcher, I want the Batch Research Folder to support ordinary Browser Draft and Run behavior, so that it remains a normal organizational surface.
65. As a quantitative researcher, I want the stable Batch Research Folder protected from deletion, so that future Batch admissions always have a valid default destination.
66. As a quantitative researcher, I want a terminal Batch-owned Run to retain the existing `Delete Research` action, so that I can remove an unwanted individual result.
67. As a quantitative researcher, I want deleting one child Run to leave its Batch and sibling Runs intact, so that cleanup is granular.
68. As a quantitative researcher, I want a deleted child Run represented by its original ID, final outcome, and deletion time in Batch detail, so that deletion cannot rewrite Batch history.
69. As a quantitative researcher, I want an independently activated DailyTrack preserved when its seed child Run is deleted, so that Research deletion does not cascade into tracking.
70. As an API client, I want cursor-paginated Batch listing, so that durable Batch history remains queryable at scale.
71. As an API client, I want Batch detail to return ordered item-to-Run mappings, aggregate state, progress, Attempt information, outcomes, and sanitized diagnostics, so that no database inspection is needed.
72. As an operator, I want a private immutable shared Alpha-and-Factor artifact bound to one Strategy Sweep's exact contracts, so that a new Attempt can reuse acknowledged upstream work safely.
73. As an operator, I want the shared artifact forbidden from cross-Batch reuse, so that Batch optimization does not create an implicit permanent Alpha cache.
74. As an operator, I want the supervisor to validate artifact binding, integrity, and fence before acknowledgement, so that corrupt or stale bytes cannot become recovery truth.
75. As an operator, I want unreferenced shared artifacts released through durable retryable garbage collection, so that RustFS cleanup failures do not change Product State.
76. As an operator, I want concurrent Data Refresh to leave a running Batch on its frozen Data Generation, so that Batch Results remain reproducible.
77. As an operator, I want peak child RSS kept within the Worker execution budget, so that shared calculation does not trade speed for unsafe memory growth.
78. As a product owner, I want Production Image evidence that Batch execution is faster than equivalent serial Runs, so that the feature demonstrates actual optimization.
79. As a product owner, I want exact Result checksums and shared-stage execution evidence in the performance gate, so that a faster final response cannot hide duplicated or changed calculation.
80. As a product owner, I want no Batch authoring, status, or control UI in V1, so that the backend calculation capability can ship independently of frontend presentation.

## Implementation Decisions

- **Domain ownership:** Add a Research Batch module that owns Batch admission
  receipts, Batch state, ordered Batch Items, Batch Attempts, durable task
  acknowledgements, cancellation receipts, live progress snapshots, and private
  artifact references. ResearchRun continues to own each Run, immutable input,
  Result Bundle, deletion, and DailyTrack activation. Publication continues to
  own immutable object recording and deletion.
- **Cross-module seam:** Research Batch uses narrow transaction-aware
  ResearchRun interfaces to prepare and atomically admit child Runs. It does not
  read or mutate ResearchRun-owned tables directly. ResearchRun deletion reports
  the deleted Run identity back through a narrow Batch membership seam so the
  Batch Item can record its deletion timestamp without changing its final
  outcome.
- **Research Batch identity:** A Batch has one stable ID, immutable Batch Kind,
  ordered Items, common Research scope, frozen Data Generation, timestamps, and
  aggregate state. It never owns a Result Bundle.
- **Research Batch Item identity:** Each Item freezes its ordinal, unique
  `item_key`, ResearchRun ID, and dependency role. Its final execution outcome
  remains durable if the ResearchRun is later deleted; Run deletion is recorded
  separately rather than replacing the final outcome with a synthetic state.
- **Batch states:** The aggregate lifecycle is `queued -> running`, with natural
  terminal states `succeeded`, `completed_with_failures`, and `failed`.
  Cancellation follows `queued -> cancelled` or
  `running -> cancelling -> cancelled`. A terminal natural outcome wins over a
  late cancellation that lost the lifecycle race. Natural completion is
  `succeeded` only when every Run succeeds, `completed_with_failures` when
  successful and failed Runs coexist, and `failed` when no Run succeeds.
  Explicit cancellation ends `cancelled` even when earlier Runs succeeded.
- **Batch Kind contract:** `factor_evaluation` contains only independent Factor
  Evaluation items. `strategy_sweep` contains exactly one Alpha and only
  parameter combinations for the one current Strategy. The request discriminator
  is explicit; Batch Kind is never inferred from optional fields.
- **Factor admission shape:** `POST /api/research-batches` with
  `batch_kind = factor_evaluation` accepts common `request_id`, Research Period,
  Liquidity Universe, and Industry Neutralization fields plus an ordered
  `factors` array. Each item contains `item_key`, optional Research Name, Alpha
  Formula, and optional Investment Hypothesis, and accepts no Strategy fields.
- **Strategy admission shape:** The same endpoint with
  `batch_kind = strategy_sweep` accepts the common fields, one `alpha` containing
  Alpha Formula and optional Investment Hypothesis, and an ordered `strategies`
  array. Each Strategy item contains `item_key`, optional Research Name,
  Holdings Count, and Rebalance Sessions.
- **Item bounds:** Each item array contains from one through twenty entries. The
  Strategy Sweep's shared Alpha is not an item and does not consume the limit.
  V1 uses this fixed hard limit rather than a configurable or benchmark-selected
  count.
- **Admission atomicity:** Compile every Alpha, resolve Data admission, validate
  every Run contract, detect duplicates, calculate the complete shared capacity
  envelope, ensure the Batch Research Folder, and freeze the current Data
  Generation before one transaction creates the Batch, Items, child Runs,
  initial progress, admission receipt, and Generation retention. Any rejection
  creates none of them.
- **Capacity admission:** The existing single-Run capacity rules continue to
  apply to every Alpha. Factor Batch planning additionally accounts for the
  union of canonical field bindings, maximum effective lookback, common Data
  matrix, and maximum sequential per-Alpha working set. Strategy Sweep planning
  accounts for the shared Alpha-and-Factor working set, private artifact, and
  one Strategy state at a time. If one complete full-Universe Research Session
  cannot fit, admission fails closed even when the item count is below twenty.
- **Duplicate Factor identity:** Compile first, then compare canonical Alpha
  Expressions. Formula source formatting, Research Name, and Investment
  Hypothesis do not make equal computation distinct. Rejection identifies both
  conflicting `item_key` values.
- **Duplicate Strategy identity:** The complete current Strategy parameter tuple
  is `(holdings_count, rebalance_every_sessions)`. Equal tuples are rejected and
  diagnostics identify both `item_key` values.
- **Idempotency:** Admission fingerprints the complete normalized submitted
  command, including Batch Kind, common scope, item order, item metadata, and
  authorable input. Replaying the same request ID and fingerprint returns the
  original outcome; a different fingerprint returns `409`.
- **Admission diagnostics:** Structural, compiler, Data, duplicate, and capacity
  rejection uses an item-aware `issues` collection and returns `422`. Field paths
  locate the common field or array item, and Formula issues retain source ranges.
- **Backend API surface:** V1 provides `POST /api/research-batches`,
  cursor-paginated `GET /api/research-batches`,
  `GET /api/research-batches/{batch_id}`, and
  `POST /api/research-batches/{batch_id}/cancel`. Admission returns `202` with
  the Batch summary and ordered `item_key` to ResearchRun ID mapping. Missing
  resources return `404`; lifecycle and idempotency conflicts return `409`.
- **Batch detail:** Detail returns Batch Kind, common frozen scope, Data
  Generation identity, aggregate state, execution timing, durable progress,
  current live progress, current or latest Attempt, ordered Items, Run
  availability, final outcome, sanitized failure, and deletion timestamp. It
  does not embed child Result Bundles; clients obtain those through the ordinary
  ResearchRun detail endpoint.
- **No Batch deletion:** V1 has no Research Batch DELETE endpoint. Batch history
  is durable. A terminal child Run retains ordinary terminal-only Research
  deletion, which cannot delete the Batch, sibling Runs, or a DailyTrack.
- **Folder behavior:** Admission places every child Run in the system-created
  Folder with stable identity `folder_batch_research` and display name
  `Batch Research`. Folder membership never defines Batch membership. Batch
  Runs keep ordinary rename, move, Create draft, and detail behavior; ordinary
  Runs may also use this Folder; only deletion of the stable Folder is rejected.
- **Frontend boundary:** V1 adds no Batch authoring, Batch list, Batch detail, or
  Batch cancellation surface to the frontend. Child Runs appear through the
  existing Research list and detail UI, including the current terminal
  `Delete Research` action.
- **Worker roles:** The one Worker executable and Production Image support three
  mutually exclusive fixed startup roles: `research`, `batch-research`, and
  `tracking`. Every Worker has one execution slot and never falls back to work
  from another role.
- **Separate claim sets:** Ordinary Research Workers claim only non-Batch
  ResearchRuns. Batch Research Workers claim only Research Batches. Tracking
  Workers claim only Tracking Advances. A Batch-owned Run is never independently
  claimable.
- **FIFO Batch claims:** Batch Workers claim the oldest claimable Batch by
  admission time and then Batch ID with durable row locking and skip-locked
  concurrency. V1 has no priority or preemption. Multiple replicas preserve
  claim/start order but do not promise completion order.
- **One Worker per Batch:** One Batch Worker owns one whole Batch until its
  Attempt ends. Items execute sequentially in submitted order. Multiple replicas
  process different Batches; no Batch is split across Workers.
- **Attempt process boundary:** One Research Batch Attempt starts exactly one
  supervised execution child for its complete lifetime. Worker or child loss
  ends the Attempt. A new Attempt always starts a new child and resumes from the
  first incomplete durable task.
- **Supervisor authority:** The child receives only immutable execution input
  and writes Attempt-scoped temporary output. It has no PostgreSQL credentials
  or RustFS publication authority. The supervisor owns claim, lease, heartbeat,
  fence, Generation Pin, task validation, acknowledgement, Result publication,
  and private artifact recording.
- **Factor Batch execution:** Build one common canonical Data slice using the
  union of required field bindings and the maximum effective lookback, resolve
  the common Liquidity Universe and Forward Return Labels once, then execute
  each Alpha's own compiled plan and Factor Evaluation independently. Sequential
  execution releases item-local working state after acknowledgement.
- **Strategy Sweep execution:** Prepare Data once and evaluate the one Alpha and
  Factor once. Add one formal Research Kernel boundary that lets the existing
  Strategy calculation consume the validated shared Alpha-and-Factor output.
  The Batch path must not copy or reimplement Alpha, Factor, or Strategy math.
- **Result publication:** Each successful Item publishes through the ordinary
  ResearchRun Result contract and includes its own provenance and ResearchRun
  identity. Factor Results contain Factor Evaluation only. Strategy Results
  contain the shared Factor Evaluation plus that item's Strategy result and
  terminal Strategy state. Batch and serial equivalence compares exact
  calculation payloads and calculation provenance while separately requiring
  each provenance record to carry its own correct ResearchRun ID.
- **Durable task boundary:** A Factor Batch acknowledges one complete
  Alpha-and-Factor unit. A Strategy Sweep acknowledges its one complete shared
  Alpha-and-Factor prerequisite and then each complete Strategy. Internal
  bounded Chunks remain cancellation and memory-control details and are not
  Batch recovery checkpoints.
- **Retry policy:** Retry count belongs to the current complete task and persists
  across Batch Attempts. A transient infrastructure failure receives no more
  than three total attempts. Permanent input, contract, capacity, integrity, or
  deterministic calculation failure receives no retry. Completed tasks are
  never recomputed.
- **Failure scope:** A permanent Factor item failure fails only its Run and later
  Factors continue. Permanent failure of the Strategy Sweep's shared
  Alpha-and-Factor task fails all dependent Runs. One Strategy failure fails
  only that Run and later Strategy items continue. Aggregate terminal state is
  derived from final Item outcomes.
- **Private shared artifact:** The complete Strategy Sweep Alpha-and-Factor
  output may be recorded as one private immutable Batch-scoped artifact bound to
  the canonical Alpha, common Research scope, Data Generation, Numeric Execution
  Contract, and semantic versions. It is not a Result, cannot be read through a
  public API, and is never reused across Batches.
- **Artifact commit:** The child writes only Attempt files. Before durable task
  acknowledgement, the supervisor verifies canonical binding, expected object
  structure, integrity checksum, and the current fence, then atomically records
  the artifact reference and task completion. Unrecorded files never become
  recovery input.
- **Artifact collection:** When all dependent Strategies are terminal and no
  Attempt is active, a transaction releases the private reference and enqueues
  newly unreferenced bytes through the existing durable Publication deletion
  queue. Collection rechecks authority and references under the Publication
  mutation lock. Failure retains the deletion record for retry without changing
  Product State. Aged Attempt files are treated as orphans only after the same
  recheck.
- **Durable progress:** Factor Batch progress contains completed and total
  Factor task counts. Strategy Sweep progress contains shared
  Alpha-and-Factor status plus completed and total Strategy counts. These values
  are monotonic recovery authority.
- **Live progress:** The current Attempt heartbeat exposes current `item_key`,
  execution phase, completed and total Research Sessions when applicable,
  estimated percentage, elapsed time, remaining-duration estimate when enough
  evidence exists, and Attempt number. It is explicitly estimated, not a Result
  or checkpoint, and may reset for the incomplete task after retry.
- **Cancellation scope:** Only the whole Batch can be cancelled. An individual
  Batch-owned Run rejects cancellation. The cancellation command has its own
  idempotent request ID. A cancelled Batch is terminal and cannot resume.
- **Running cancellation:** Cancellation records `cancelling`, advances the
  execution fence before asking the child to stop, waits up to five seconds for
  cooperative exit, terminates an unresponsive child, confirms exit, releases
  the Generation Pin, cleans incomplete state, and finally records `cancelled`.
- **Cancellation retention:** Cancellation is prospective. Already acknowledged
  task outcomes and already-published Results remain authoritative; successful
  Strategy Runs may still seed or retain DailyTracks. Unfinished Runs become
  cancelled. Live progress, unchecked output, incomplete Checkpoints, Attempt
  files, and now-unused shared artifacts are discarded or collected.
- **Data Generation safety:** Admission freezes one Data Generation and creates
  Batch-scoped retention. Claim replaces admission retention with an Attempt
  Pin. Every retry uses the same Generation even if Refresh advances the Dataset
  Head. Pin release occurs only after confirmed child exit and terminal durable
  state.
- **Hard cut:** Implement one current Research Batch contract. Add no legacy
  aliases, compatibility readers, fallback queue, migration path, alternate
  Batch schema version, or second calculation implementation.

## Testing Decisions

- **Primary test seam:** Exercise Batch behavior through the public Batch HTTP
  API and the real Core runtime with PostgreSQL, RustFS, the Batch Worker
  supervisor, and a real execution child. Assert returned resources, durable
  Product State, published Results, object lifecycle, Worker events, and restart
  behavior. This is the highest existing seam and should cover most feature
  behavior without mocking owned dependencies.
- **Admission contract coverage:** Test both discriminated Batch Kinds, one-item
  and twenty-item boundaries, empty and twenty-one-item rejection, unknown or
  mixed fields, invalid common scope, invalid per-item input, duplicate
  `item_key`, canonical Factor duplicates, duplicate Strategy tuples, source-
  ranged Formula diagnostics, and capacity rejection. Every rejection must
  prove zero Batch, Run, receipt, retention, and object state.
- **Atomic idempotency coverage:** Test exact replay, conflicting replay,
  concurrent duplicate admission, transaction failure, and restart after an
  uncertain response. Assert one Batch, the expected number of Runs, one
  admission receipt, stable ordered IDs, and one frozen Data Generation.
- **API behavior coverage:** Test cursor pagination, detail ordering, missing
  resources, sanitized failures, Result lookup through child Run detail,
  terminal child Run deletion, Batch Item deletion tombstone, retained sibling
  Runs, retained DailyTrack, and absence of a Batch DELETE route.
- **Folder behavior coverage:** Test creation and stable identity of the Batch
  Research Folder, default placement, ordinary rename and move of child Runs,
  ordinary Run use of the Folder, Browser Draft behavior, and rejection of
  Folder deletion without using Folder membership as Batch identity.
- **Worker role architecture coverage:** Extend the current Worker-role tests to
  require `batch-research`, freeze it at startup, enforce one slot, prove the
  three disjoint claim sets, and prove that an ordinary Research Worker cannot
  claim a Batch-owned Run. Keep these as boundary tests rather than assertions
  over private helper calls.
- **FIFO and replica coverage:** With real PostgreSQL claims, admit ordered
  Batches, hold the first claim at an execution barrier, start multiple Batch
  Workers, and prove each replica claims a distinct next Batch in FIFO order.
  Do not assert completion order across replicas.
- **Factor execution coverage:** Compare a Factor Batch with the same ordered
  ordinary Factor Evaluation Runs on one frozen Generation. Assert exact Result
  semantic checksums, equal calculation contracts and semantic versions,
  correctly distinct owning ResearchRun IDs, one common Data/Universe/Label
  preparation, one independent Alpha-and-Factor execution per item,
  deterministic request order, and bounded peak RSS.
- **Strategy execution coverage:** Compare a Strategy Sweep with the same
  ordered ordinary Strategy Backtest Runs. Assert one shared Data preparation,
  one Alpha execution, one Factor execution, one Strategy execution per item,
  exact Factor/Strategy/terminal-state semantic checksums, equal calculation
  contracts and semantic versions, correctly distinct owning ResearchRun IDs,
  and bounded peak RSS. Observe stage events and I/O metrics rather than mocking
  or counting private function calls.
- **Kernel equivalence coverage:** Preserve the existing row-reference versus
  columnar Alpha/Factor/Strategy and bounded continuation equivalence tests. Add
  direct equivalence for the formal shared Alpha-and-Factor-to-Strategy seam so
  Batch execution and the ordinary pipeline cannot drift algorithmically.
- **Progress coverage:** Assert durable counts before, during, and after each
  complete task; live phase/session progress during an active task; honest
  estimated fields; terminal timing; and current-task live reset after retry
  without regression of completed counts.
- **Failure-scope coverage:** Inject permanent failure into a middle Factor,
  shared Strategy prerequisite, and one middle Strategy item. Assert the exact
  affected Runs, continuation of independent work, aggregate terminal state,
  published successful Results, and sanitized diagnostics.
- **Retry and recovery coverage:** Exercise transient failure before task
  acknowledgement, after acknowledged task publication, during private artifact
  staging, and after artifact recording. Kill the Worker and child separately,
  expire leases, restart the runtime, and assert a new Attempt/child resumes at
  the first incomplete task without recomputing completed tasks. Test three-
  attempt exhaustion and permanent no-retry behavior.
- **Artifact integrity coverage:** Test valid reuse inside the same Strategy
  Sweep, rejection of corrupt bytes, binding mismatch, stale fence, obsolete
  calculation contract, and attempted cross-Batch reuse. Assert that no invalid
  artifact can acknowledge a task or publish a Result.
- **Cancellation coverage:** Test queued cancellation, running cooperative exit,
  forced exit within the five-second budget, cancellation during retry wait,
  lost supervisor, stale child publication, cancellation racing final
  acknowledgement, exact idempotent replay, and request-ID conflict. Assert
  confirmed child exit and Generation Pin release before terminal `cancelled`.
- **Cancellation retention coverage:** Complete some items, cancel the Batch, and
  assert completed Results and any independent DailyTrack remain while every
  unfinished Run is cancelled and incomplete Checkpoints, Attempt files, live
  heartbeat, and private shared artifacts become unreferenced and collectible.
- **Publication and garbage-collection coverage:** Reuse the existing real
  Publication integration seam to test atomic Result and private artifact
  recording, reference release, deletion queue retries, orphan cutoffs, and
  rechecks racing a new reference. Object deletion failure must not modify Batch
  or Run outcome.
- **Refresh isolation coverage:** Advance the Dataset Head while a Batch is
  running and while it is retrying. Assert every child Result remains bound to
  the originally admitted Generation and collection cannot remove the active
  Generation before confirmed terminal cleanup.
- **Restart coverage:** Restart API, Batch Worker, PostgreSQL connection, and
  RustFS availability at the existing acceptance seams. Assert Batch list,
  detail, progress, receipts, Item outcomes, retry count, artifact binding, and
  deletion tombstones remain stable.
- **Performance baseline:** In the same Production Image and against the same
  Data Generation, compare a representative multi-item Factor Batch and
  Strategy Sweep with strictly serial ordinary Runs. Record total elapsed time,
  Data I/O, phase timing, item count, object bytes, cleanup, and child peak RSS.
  Batch elapsed time must be lower than the serial baseline and RSS must remain
  within the configured execution budget.
- **Performance correctness:** A timing win alone does not pass. The evidence
  must prove exact semantic checksums, expected shared-stage execution counts,
  deterministic repeated output, Strategy sensitivity to Holdings Count and
  Rebalance Sessions, finite values, NAV/drawdown validity, and Factor Coverage.
- **Production Image gate:** Extend the existing Production Image Smoke Test to
  admit and execute both Batch Kinds through real HTTP, PostgreSQL, RustFS,
  Batch Worker, child, publication, restart, cancellation, and cleanup. Capture
  image identity, Worker events, exit codes, timing, RSS, request/response
  evidence, Product State before/after cleanup, and Result checksums.
- **Determinism and diagnostics:** Fix clocks, UUID sources, random seeds, Data
  Generation, formulas, parameter sets, and expected task ordering. Use bounded
  condition polling rather than arbitrary sleeps, and emit current Batch state,
  Attempt state, Worker events, object references, and seed on timeout.
- **Frontend test boundary:** Add no Batch frontend or Batch browser E2E in V1.
  Existing Research list/detail tests remain responsible for displaying and
  deleting the ordinary child Runs; Batch behavior is accepted at the backend
  HTTP and Production Image seams.
- **Release rule:** Do not claim optimization, correctness, recovery, or cleanup
  from source inspection or focused unit tests alone. The complete real-
  dependency acceptance and final Production Image gate must pass together.

## Out of Scope

- A Batch authoring, Batch list, Batch detail, progress, or cancellation UI.
- A public frontend entry point or navigation route for Research Batch.
- A mixed Batch containing both Factor Evaluation and Strategy Sweep items.
- A public `alpha_groups` structure or any other implicit grouping abstraction.
- Multiple Alphas feeding one Strategy Sweep.
- Multiple Strategy algorithms or user-selectable Strategy implementations.
- Implicit Cartesian products between Alphas and Strategy parameters.
- More than twenty submitted items in one Batch.
- Per-item cancellation, retry, resume, reprioritization, or reordering.
- Resuming a terminal cancelled Batch.
- Whole-Batch deletion or cascading deletion of all child Runs.
- Parallel item execution inside one Batch or splitting one Batch across
  multiple Workers.
- Priority queues, preemption, deadlines, or fairness classes beyond FIFO Batch
  claiming and the fixed item limit.
- One shared queue consumed interchangeably by ordinary Research and Batch
  Research Workers.
- A second Research Kernel, calculation engine, Worker image, or deployment
  artifact for Batch execution.
- Chunk-level durable Batch recovery or public partial Results.
- Cross-Batch Alpha, Factor, Data, or Strategy caching.
- A permanent Alpha store or a user-visible shared Alpha-and-Factor artifact.
- Automatic DailyTrack creation for successful Strategy items.
- A Batch-level combined Result, leaderboard, comparison report, or best-
  parameter selection.
- Compatibility aliases, legacy Batch payloads, schema migrations, fallback
  queues, or parallel old/new execution paths.
- An external queue, workflow engine, distributed scheduler, or event bus.
- Changing ordinary ResearchRun or DailyTrack calculation semantics.

## Further Notes

- This Spec uses the domain vocabulary in the project glossary and implements
  the accepted decisions in ADR-0214, ADR-0216, and ADR-0218.
- Research Batch is not Batch-Incremental Equivalence. The latter is a numeric
  correctness property; Research Batch is a durable product and orchestration
  resource.
- The primary expected speedup is Strategy Sweep reuse of one Data,
  Alpha, and Factor calculation. Factor Batch optimization is intentionally
  narrower: it shares common preparation while keeping every Alpha and Factor
  calculation independent.
- The Batch Research Folder is only the default organizational destination.
  Immutable Batch Item membership, not Folder membership, is the source of
  Batch ownership and history.
- `cancelled` means remaining execution stopped. It does not invalidate or
  delete already succeeded child Runs. Explicit terminal Research deletion
  remains the only operation that removes one child Run and its unreferenced
  Result.
- The testing seam was agreed during design: public Batch HTTP behavior plus the
  real PostgreSQL/RustFS/Batch Worker/child/Publication chain is the primary
  acceptance boundary, with the Production Image as the release boundary.

## Comments

- 2026-08-24: Synthesized from the completed Research Batch design discussion
  and published with `ready-for-agent` triage using `to-spec`.
