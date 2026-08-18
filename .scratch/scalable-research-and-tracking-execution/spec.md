# Scalable Long Research and Daily Tracking Execution

**Status:** complete

## Problem Statement

ThesisTrace cannot currently support the core research journey of running a valid
Alpha Formula from 2010 through the latest covered Research Session over a large
Universe. Admission treats Estimated Total Research Work as a hard budget, so a
semantically valid long Research Period can fail with
`ALPHA_RUN_WORK_EXCEEDS_LIMIT` before execution. When a Run is admitted, the
current execution path still materializes too much of the selected period as
Python objects and provides no durable Chunk boundary from which expensive work
can resume.

The execution topology compounds that problem. One mixed Worker polls
ResearchRun and DailyTrack work instead of giving each workload an independently
scaled capacity pool. A Worker process is not an explicit one-Run resource
envelope, Research work cannot expose useful committed progress, and an
infrastructure failure can force a long historical calculation to repeat more
work than necessary. Cancellation also lacks a process boundary that can prove
calculation has stopped before protected Data Generation resources are released.

DailyTrack has a different workload but is currently forced through similarly
coarse execution behavior. Catch-up work needs a bounded, fair Target; failures
must not partially move the Tracking Head; transient retries must not monopolize
a Worker; and Stop must not report `stopped` while an old calculation can still
run or publish. At the same time, adding Research-style private checkpoints to
short incremental Tracking work would create unnecessary Generation binding,
recovery, and garbage-collection complexity.

The system also lacks one enforceable capacity contract connecting admission,
runtime containment, deployment limits, and performance acceptance. Without
that contract, increasing the supported date range risks replacing an admission
error with unbounded memory, silent replanning, long periods without progress,
or several Runs competing inside one Worker process.

This is a development-stage product. Replacing the execution contract must not
introduce a V2 engine, migration framework, compatibility reader, fallback path,
or duplicate runtime. Product State created under result-changing old semantics
may be reset, but the already downloaded Canonical Data Store must not be erased
by the ordinary development reset.

## Solution

ThesisTrace will admit Research according to Estimated Peak Execution Footprint
rather than Estimated Total Research Work. A Research Period from 2010 through
the latest covered session is valid when its Formula is structurally valid and
one complete eligible Universe for one Research Session fits the configured
Research Worker Capacity. Total work remains visible for progress and duration
guidance but does not reject or deprioritize the Run.

Admission will freeze one deterministic execution plan made of contiguous,
full-Universe Research Session Chunks. The planner selects the largest fixed
Chunk size from 1 through 63 sessions that fits the execution-memory budget and
is estimated to complete within the sizing target. Research then executes those
Chunks sequentially through one PyArrow and NumPy columnar path.

One Research Worker owns one ResearchRun Attempt at a time. Its supervisor owns
the claim, lease, fence, frozen Data Generation Pin, private staging,
Checkpoints, and final publication. Exactly one read-only execution child lives
for that Attempt, computes Chunks sequentially, and waits for a durable
supervisor acknowledgement after each Chunk. Each committed private Checkpoint
contains only bounded continuation state and references to immutable staged
result partitions. Infrastructure retry resumes the same ResearchRun from the
latest fully validated Checkpoint; successful completion still publishes one
atomic immutable Result.

Research and Tracking use separate fixed-role Worker pools built from the same
Production Image and executable. Every Worker has one execution slot, and
system concurrency increases only by adding Worker replicas. Development runs
one 2-vCPU, 2-GiB Research Worker and one 2-vCPU, 2-GiB Tracking Worker. Each
role has an independent deployment-level capacity declaration and reserves 25
percent of container memory outside its execution planner.

DailyTrack will deliberately use Head-only recovery. A persistent Tracking
Advance freezes a capacity-planned Target containing the oldest 1 through 63
unpublished sessions. Every Attempt uses one current Data Generation for its
whole lifetime and either atomically publishes one Tracking Checkpoint that
moves the Head across the complete Target or publishes nothing. A failed
Attempt discards unpublished work; a later Attempt starts from the unchanged
authoritative Tracking Head and recomputes the same frozen Target, possibly
against a newer Data Generation. No private Tracking execution checkpoint is
created.

Transient Tracking failures receive one bounded three-Attempt Cycle with fair
queue rotation and fixed retry delays. Permanent failures block immediately.
Only an explicit user Retry can reactivate the same Advance, and capacity is
reevaluated before a new Cycle begins. Dataset Head movement, service restart,
or capacity changes do not silently unblock a Track.

Research Cancel and DailyTrack Stop will use the supervisor and execution child
as a confirmed termination boundary. While the supervisor remains alive, the
operation has a five-second total confirmation budget and may escalate from
cooperative shutdown to child termination. Terminal `cancelled` or `stopped`
is exposed only after the child has exited, the old fence prevents publication,
and the Attempt-scoped Pin can safely be released. Lost-supervisor recovery is
safety-first and may exceed five seconds.

The replacement is a hard cut to one current Numeric Execution Contract. The
runtime will contain no old-contract dispatcher or alternate engine. Ordinary
`dev:reset` will clear Product State and preserve Canonical Data; a separate
explicit destructive operation will erase downloaded Canonical Data when that
is actually intended.

## User Stories

1. As a quantitative researcher, I want to run Research from 2010 through the latest covered session, so that I can evaluate an Alpha over a complete useful market history.
2. As a quantitative researcher, I want a long but valid Research Period admitted when its peak execution slice fits, so that total historical work is not mistaken for invalid input.
3. As a quantitative researcher, I want an explicit rejection when even one complete Research Session cannot fit the Worker memory envelope, so that capacity failures are understandable before execution.
4. As a quantitative researcher, I want cross-sectional operators to see the complete eligible Universe for each session, so that Chunking never changes Formula meaning.
5. As a quantitative researcher, I want long Research to preserve exact numeric and missing-value semantics, so that performance optimization cannot change scientific results.
6. As a quantitative researcher, I want my accepted Run to remain bound to one immutable input and one Data Generation, so that later data publication cannot alter the question being executed.
7. As a quantitative researcher, I want one final immutable Result only after the complete Run succeeds, so that partial work cannot be mistaken for research evidence.
8. As a quantitative researcher, I want infrastructure recovery to remain under the same ResearchRun, so that operational retries do not create duplicate research history.
9. As a quantitative researcher, I want an expensive long Run to resume from committed work after a Worker failure, so that one transient failure does not repeat the whole period.
10. As a quantitative researcher, I want a retry to validate its Checkpoint before resuming, so that corrupted or incompatible continuation state cannot silently affect my Result.
11. As a quantitative researcher, I want committed progress reported while a long Run executes, so that I can distinguish useful forward movement from a stalled process.
12. As a quantitative researcher, I want warm-up progress shown separately from Research Period progress, so that prerequisite calculation is visible without overstating completed research.
13. As a quantitative researcher, I want an in-flight session shown as current work rather than completed work, so that transient liveness does not misrepresent durable progress.
14. As a quantitative researcher, I want a remaining-duration estimate only after enough committed work exists, so that the product does not fabricate an ETA from elapsed time alone.
15. As a quantitative researcher, I want to cancel a queued Run immediately, so that work that has not started consumes no execution resources.
16. As a quantitative researcher, I want a running Run to show `cancelling` until its calculation has actually stopped, so that cancellation status is truthful.
17. As a quantitative researcher, I want cancellation to prevent every later Checkpoint or Result commit from the old Attempt, so that stopped work cannot publish late.
18. As a quantitative researcher, I want ordinary cancellation to finish promptly while the Worker supervisor is healthy, so that I can recover the execution slot without a long wait.
19. As a quantitative researcher, I want a safety-first status when a Worker host is lost during cancellation, so that the product does not release data or report completion before old ownership is dead.
20. As a quantitative researcher, I want terminal failure to explain whether the problem is capacity, data, calculation, integrity, or exhausted infrastructure retry, so that I know whether changing the research question can help.
21. As a quantitative researcher, I want Estimated Total Research Work used for guidance rather than queue priority, so that a newer short Run cannot continually displace my older long Run.
22. As a quantitative researcher, I want ResearchRuns claimed in stable FIFO order, so that waiting behavior is predictable.
23. As a quantitative researcher, I want a transiently retrying Run to retain its original FIFO position, so that infrastructure failure does not send it to the back of the research queue.
24. As a quantitative researcher, I want one Run to use one Worker slot for its Attempt, so that several Runs cannot unexpectedly compete inside one process memory budget.
25. As a quantitative researcher, I want more simultaneous ResearchRuns achieved by adding Workers, so that concurrency scales predictably without changing one Run's semantics.
26. As a quantitative researcher, I want a single Run executed sequentially by one Worker rather than split across Workers, so that recovery and numeric ordering remain understandable.
27. As a quantitative researcher, I want Formula, Factor Evaluation, Strategy Backtest, and finalization included in the same execution plan, so that the optimization covers the complete product result rather than Alpha alone.
28. As a quantitative researcher, I want financial and market Alpha fields to use the same bounded execution path, so that long Research support is not limited to price-only examples.
29. As a quantitative researcher, I want the canonical reference momentum Formula to finish within the accepted Production Image performance gate, so that the long-history product claim is measurable.
30. As a quantitative researcher, I want a warm repeated Run to benefit from existing immutable data caches without inheriting another Run's Product State, so that speed improves without compromising isolation.
31. As a DailyTrack user, I want my published Tracking Head to remain the sole authoritative recovery point, so that failed unpublished work cannot become ambiguous state.
32. As a DailyTrack user, I want catch-up divided into bounded Advances, so that a long period of downtime does not create one unbounded Tracking execution.
33. As a DailyTrack user, I want each Advance to freeze an exact ordered Target, so that Retry cannot silently absorb new sessions or change the meaning of the pending work.
34. As a DailyTrack user, I want a successful Advance to move the Head across its whole Target atomically, so that I never observe a partially published Target.
35. As a DailyTrack user, I want a failed Advance to leave the Head unchanged, so that the next Attempt has one unambiguous predecessor.
36. As a DailyTrack user, I want a failed Attempt to discard unpublished work and recompute from the Head, so that short incremental recovery remains simple and correct.
37. As a DailyTrack user, I want one Attempt to use one stable Data Generation, so that sessions inside one published Checkpoint never mix Generations.
38. As a DailyTrack user, I want a later Attempt to use the then-current Generation only when it contains the same predecessor and frozen Target, so that corrections can be used without rewriting coordinates.
39. As a DailyTrack user, I want a calendar mismatch treated as a data-integrity failure, so that Retry cannot expand or shrink my frozen Target to hide inconsistent data.
40. As a DailyTrack user, I want transient failure retried a bounded number of times, so that temporary infrastructure trouble can recover without an infinite loop.
41. As a DailyTrack user, I want permanent data, calculation, capacity, integrity, or equivalence failures to block immediately, so that deterministic problems are not repeated automatically.
42. As a DailyTrack user, I want only my explicit Retry to reactivate a blocked Advance, so that new data or a restart cannot silently restart failed work.
43. As a DailyTrack user, I want Retry to preserve the same Target while reevaluating current Worker Capacity, so that remediation does not mutate the pending business boundary.
44. As a DailyTrack user, I want a one-session Target retained when it cannot currently fit, so that the blocked state has a concrete Advance that can later be retried.
45. As a DailyTrack user, I want retry waiting and Cycle position visible, so that I know whether the system is computing, waiting, or needs my action.
46. As a DailyTrack user, I want authoritative Head and lag shown separately from in-flight phase and session, so that temporary progress cannot be confused with published history.
47. As a DailyTrack user, I want several lagging Tracks to rotate fairly, so that one large catch-up cannot starve all other Tracks.
48. As a DailyTrack user, I want a retrying Track to rejoin the fair queue after its delay, so that it does not hold a Worker slot while waiting.
49. As a DailyTrack user, I want separate Tracking Worker replicas to process different Tracks safely, so that Tracking throughput scales horizontally.
50. As a DailyTrack user, I want concurrent Advances for the same Track prevented by claims and fences, so that two Workers cannot move one Head independently.
51. As a DailyTrack user, I want Stop to show `stopping` while a calculation child still exists, so that terminal status reflects real resource ownership.
52. As a DailyTrack user, I want Stop to cancel the active Advance, Cycle, retry eligibility, and pending claim, so that no later Worker can restart the stopped Track.
53. As a DailyTrack user, I want a blocked or idle Track to stop immediately when no child owns resources, so that unnecessary waiting is avoided.
54. As a DailyTrack user, I want a running Stop to prevent late Tracking publication, so that an old child cannot move the Head after my request.
55. As a DailyTrack user, I want a Track to become `stopped` only after its child exits and its Generation Pin is safe to release, so that Stop is confirmed rather than optimistic.
56. As a DailyTrack user, I want a stopped Track's Working Cache removed while its Checkpoints remain, so that disposable storage is reclaimed without deleting authoritative history.
57. As a DailyTrack user, I want `stopping` to count against the Active DailyTrack Limit, so that an unconfirmed child cannot free capacity prematurely.
58. As a DailyTrack user, I want Retry and Delete unavailable while a Track is stopping, so that lifecycle actions cannot race termination.
59. As a DailyTrack user, I want the existing limit of ten non-stopped Tracks enforced transactionally, so that concurrent activation cannot exceed supported capacity.
60. As a Worker operator, I want Research and Tracking in independent fixed-role pools, so that heavy historical work cannot consume incremental Tracking capacity.
61. As a Worker operator, I want one Production Image and executable for both roles, so that pool separation does not create two engines to maintain.
62. As a Worker operator, I want a Worker role fixed at startup with no fallback to the other queue, so that capacity and scheduling remain explicit.
63. As a Worker operator, I want one execution slot per Worker, so that the declared CPU and memory envelope is enforceable.
64. As a Worker operator, I want Research and Tracking pool capacities configured independently, so that production can match their different workload profiles.
65. As a Worker operator, I want startup to reject a container whose actual limits are below its declared role capacity, so that planning never assumes unavailable resources.
66. As a Worker operator, I want development to use a reproducible 2-vCPU and 2-GiB envelope per Worker, so that local performance and capacity defects are visible early.
67. As a Worker operator, I want execution planning limited to 75 percent of Worker memory, so that the supervisor, clients, serialization, and runtime retain headroom.
68. As a Worker operator, I want Arrow and NumPy execution threads bounded by assigned Worker CPU, so that vectorized kernels do not oversubscribe the slot.
69. As a Worker operator, I want increasing replica count to increase concurrency without changing accepted plans, so that horizontal scaling is operational rather than semantic.
70. As a Worker operator, I want capacity reductions to require draining incompatible frozen work, so that rollout cannot silently replan an accepted Run or Advance.
71. As a Worker operator, I want idle maintenance bounded behind claimable product work, so that Publication deletion cannot starve Research or Tracking.
72. As a Worker operator, I want structured lifecycle logs keyed by role, Run or Track, Attempt, Chunk or Target, and failure category, so that stalled and failed execution can be diagnosed.
73. As a Research platform maintainer, I want PyArrow projection, filtering, buffers, null masks, and RecordBatch interchange used directly, so that the full Research Period is not expanded into Python rows.
74. As a Research platform maintainer, I want NumPy used only for vectorized kernels not supplied by Arrow, so that the backend stays small and established.
75. As a Research platform maintainer, I want deterministic session and instrument ordering before order-sensitive calculation, so that columnar execution preserves the Numeric Execution Contract.
76. As a Research platform maintainer, I want dead Chunk intermediates released promptly, so that peak memory is bounded by Chunk shape rather than Research Period length.
77. As a Research platform maintainer, I want only bounded rolling, Label, Factor, Strategy, and checksum continuation retained between Chunks, so that live state does not grow with history length.
78. As a Research platform maintainer, I want growing Strategy Daily Observations streamed to immutable staged partitions, so that final output does not require one full-period in-memory payload.
79. As a Research platform maintainer, I want completed Alpha cross-sections, matured stock-level Labels, and daily Factor observations folded and released, so that private checkpoints do not become historical data warehouses.
80. As a Research platform maintainer, I want the supervisor alone to write Product State and Publication objects, so that child termination and stale execution cannot race durable commits.
81. As a Research platform maintainer, I want every child to wait for Checkpoint acknowledgement before its next Chunk, so that computation cannot outrun the durable recovery boundary.
82. As a Research platform maintainer, I want loss of the supervisor connection to terminate the child, so that an orphan cannot continue reading or calculating indefinitely.
83. As a Research platform maintainer, I want one child lifecycle per Attempt with no process reuse, so that lease, Pin, cancellation, and resource accounting share one boundary.
84. As a Research platform maintainer, I want checksum, input, Generation, boundary, compiler, numeric, and calculation-contract mismatches to fail explicitly, so that recovery never performs a best-effort merge.
85. As a Research platform maintainer, I want private Checkpoints and staged objects collectible after terminal state or Research deletion, so that resumability does not create permanent hidden storage.
86. As a Research platform maintainer, I want exact Chunked and uninterrupted execution equivalence, so that Chunk boundaries never become a second calculation contract.
87. As a product maintainer, I want exactly one active Numeric Execution Contract, so that runtime behavior has one current meaning.
88. As a product maintainer, I want Product State created under a result-changing old contract refused rather than migrated or reinterpreted, so that stale history cannot silently continue under new semantics.
89. As a product maintainer, I want the ordinary development reset to preserve downloaded Canonical Data, so that a hard Product State cut does not require another long data collection.
90. As a product maintainer, I want complete Canonical Data deletion to require a separate explicit command, so that reset and erase have unambiguous destructive scopes.
91. As a product maintainer, I want browser references to reset Product resources treated as stale, so that development reset does not require a compatibility layer.
92. As a release owner, I want the complete Production Image path benchmarked rather than an isolated Alpha function, so that performance evidence includes data reads, Factor, Strategy, Checkpoints, and publication.
93. As a release owner, I want cold and warm performance measured separately over repeated samples, so that caching effects are visible and reproducible.
94. As a release owner, I want peak RSS, first Checkpoint latency, cancellation latency, and final execution duration enforced together, so that a faster Run cannot pass by violating containment or operability.
95. As a release owner, I want the fixed reference range retained as a reproducible regression workload while later data growth is monitored, so that the gate remains comparable without limiting product support to 2026.

## Implementation Decisions

### Product and contract cut

- This feature replaces the current Research and Tracking execution paths in
  place. It does not add a V2 service, engine selector, compatibility adapter,
  migration, fallback, or dual-write period.
- The active runtime executes exactly one calculation kernel and Numeric
  Execution Contract. ResearchRuns and DailyTracks record that identity for
  validation and provenance, not runtime dispatch.
- A result-changing contract update makes older Product State non-executable.
  Development resolves the hard cut by resetting Product State while preserving
  the mounted Canonical Data Store and current Dataset Head.
- Development exposes a separate identity-checked erase operation for the rare
  case where PostgreSQL, RustFS, and Canonical Data must all be removed.

### Research admission and frozen planning

- ResearchRun admission retains structural Formula limits, effective-lookback
  limits, coverage validation, and immutable Data Generation selection.
- Estimated Total Research Work is recorded for progress, duration guidance,
  warning, and telemetry. It is neither an admission limit nor a queue-priority
  input.
- Estimated Peak Execution Footprint is the execution capacity boundary. The
  smallest legal slice is one complete eligible Universe for one Research
  Session, including every field and calculation state required by the Formula,
  Factor Evaluation, and Strategy Backtest.
- The planner chooses the largest fixed Chunk session count from 1 through 63
  that fits the 75-percent execution-memory budget and is estimated to execute
  within 30 seconds on the declared Research Worker Capacity.
- The 30-second value is a sizing target. If one complete session fits memory
  but is estimated to take longer, admission uses one-session Chunks and records
  that the target is exceeded. Only a single complete session that cannot fit
  memory is rejected.
- The selected capacity facts, fixed Chunk size, ordered warm-up sessions, and
  ordered Research Period boundaries are frozen with the Run. Later Attempts do
  not shrink, expand, or replan them.
- Every Chunk is a contiguous Research Session range and contains the complete
  eligible Universe for each session. Instrument sharding is not a semantic,
  scheduling, or checkpoint boundary.

### Columnar Research execution

- PyArrow is the single backend for selective Parquet scanning, projection,
  filtering, Arrow buffers, null masks, and RecordBatch exchange. NumPy supplies
  vectorized numeric kernels only where Arrow is insufficient.
- Canonical Market and Financial Data are read only for the current Chunk,
  required fields, relevant Universe membership, and required warm-up.
- Data is deterministically ordered by Research Session and instrument before
  order-sensitive calculation.
- Alpha plan nodes consume typed columnar arrays and release dead intermediates
  during the Chunk. Whole-period tables are not converted to Python row lists,
  full-period dictionaries, or defensive deep-copy graphs.
- Strategy rules may extract bounded scalar or compact per-session state, but
  they do not convert the whole Chunk to Python rows.
- Null handling, dtype conversion, sorting, floating-point association, and
  canonical serialization remain explicit parts of the one Numeric Execution
  Contract. Required bounded copies are allowed when correctness demands them.

### Research Attempt, child, and checkpoint boundaries

- ResearchRun is the user-visible business lifecycle, Attempt is the execution
  child lifecycle, and Chunk is the durable private checkpoint boundary.
- A Research Worker supervisor claims one eligible Run and creates exactly one
  execution child for the Attempt. The child executes the frozen Chunks in order
  and exits at Attempt end; it is never pooled or reused.
- The supervisor exclusively owns the Attempt lease, fence, frozen Data
  Generation Pin, Checkpoint chain, Staged Result Partitions, and final
  publication authority.
- The child has read-only access to the frozen mounted Data Generation and no
  PostgreSQL or RustFS write authority. It returns bounded calculation output to
  the supervisor.
- After each Chunk, the supervisor validates the result and current fence,
  stages immutable payloads, commits the corresponding Checkpoint, and sends an
  acknowledgement. The child cannot start the next Chunk before that
  acknowledgement.
- A lost supervisor connection causes the child to exit without further work or
  publication.
- A Research Execution Checkpoint is private, immutable, fenced, checksummed,
  and chained. It binds immutable Run input, frozen Data Generation, compiler
  and calculation contracts, the highest contiguous completed boundary,
  bounded continuation state, and ordered staged payload references.
- Retry resumes only from the newest fully verified Checkpoint. A mismatch is a
  terminal integrity failure; it does not trigger restart-from-zero,
  best-effort merge, alternate Generation selection, or plan changes.

### Bounded continuation and final Result

- Cross-Chunk continuation may contain only bounded rolling-operator tails,
  unmatured 1-, 5-, and 20-session Label inputs, ordered Factor aggregate state,
  Strategy account and scheduling state, and incremental checksum state.
- Completed Alpha cross-sections, matured stock-level Labels, and daily Factor
  observations are folded into bounded state and released before the next
  Chunk. They are not retained as checkpoint datasets.
- Growing Strategy Daily Observations are written to private immutable Staged
  Result Partitions. The Checkpoint retains their ordered checksum references
  rather than a growing reconstructed payload.
- Finalization does not recompute completed Chunks or combine approximate
  per-Chunk summaries. It preserves original session order and numeric
  association.
- Checkpoints and staged objects are not user-visible Results. One successful
  Attempt atomically publishes exactly one immutable Result Bundle. Terminal
  failure, cancellation, success cleanup, or Research deletion ends private
  checkpoint ownership and makes unreferenced objects collectible.

### Research progress

- Each committed Chunk atomically advances durable ResearchRun Progress with
  current phase, completed and total Research Period sessions, and last
  completed Research Session.
- Warm-up-only Checkpoints expose their own completed and total warm-up sessions
  while Research Period completion remains zero.
- The active Attempt heartbeat may expose transient phase and current session.
  It never marks that session complete and disappears with the Attempt.
- After at least two committed Chunks, the system may estimate remaining
  duration from observed per-Run throughput and remaining total work. The UI
  labels it as a revisable estimate, not an SLA or completion guarantee.
- Public progress never exposes Alpha Values, Factor observations, staged
  payloads, provisional Strategy observations, or provisional metrics.

### Research scheduling, retry, and cancellation

- Research Workers claim eligible ResearchRuns from one PostgreSQL-backed strict
  FIFO queue ordered by original admission time and stable Run identity. Atomic
  row locking and skip-locked claiming permit different replicas to claim
  different Runs.
- Estimated work and date length never affect priority. Infrastructure retry
  retains the Run's original FIFO position.
- A ResearchRun has at most three total Attempts. Automatic retry is limited to
  unexpected Worker loss and transient PostgreSQL, RustFS, network, timeout, or
  Publication unavailability.
- Confirmed cgroup OOM, execution-memory breach, invalid Canonical Data,
  calculation or domain failure, integrity or contract mismatch, numeric
  failure, Result budget failure, and every other permanent error terminate on
  the first occurrence.
- A publication retry reuses validated continuation and staged payloads instead
  of recomputing completed Chunks. User cancellation never creates another
  Attempt.
- Queued cancellation is immediately terminal because no execution child owns
  resources.
- Running cancellation atomically moves the Run and Attempt to `cancelling`,
  advances the fence, and signals the supervisor. The child checks cancellation
  before and after each session and between bounded expensive operator stages.
- While the supervisor remains alive, cooperative shutdown, escalation to child
  termination, exit confirmation, Pin release, and terminal persistence share
  one five-second total budget.
- Terminal `cancelled` is recorded only after child exit. When the supervisor,
  container, or host is lost, durable intent and fencing remain authoritative;
  replacement recovery waits until old lease and ownership cannot be live even
  if that exceeds five seconds.

### Worker topology and capacity

- The Production Image and Worker executable expose exactly two mutually
  exclusive startup roles: `research` and `tracking`. Role is frozen at startup
  and cannot fall back to the other queue.
- Every Worker has one execution slot, one supervisor, and at most one execution
  child. One Worker never executes several ResearchRuns or Tracking Advances
  concurrently.
- System concurrency equals the number of Worker replicas. One ResearchRun or
  one Tracking Advance Attempt is never distributed across several Workers.
- Research Worker Capacity and Tracking Worker Capacity are independent
  deployment declarations consumed by their planners and enforced across each
  complete Worker container.
- Development and test use 2 vCPU and 2 GiB per Worker role. Execution planning
  receives at most 1.5 GiB and two compute threads; the remaining 512 MiB covers
  the supervisor, Python, clients, serialization, and bounded variation.
- The default development topology therefore allocates approximately 4 vCPU and
  4 GiB across its one Research Worker and one Tracking Worker before API, web,
  PostgreSQL, and RustFS overhead.
- Worker startup fails when actual cgroup limits are below the role declaration.
- Increasing a pool's capacity or replica count does not alter existing frozen
  work. Decreasing capacity requires draining or stopping non-terminal work
  whose frozen plan no longer fits.
- When idle, either role may reclaim at most one pending shared Publication
  object per poll under the Publication mutation fence. Product work is checked
  first. Tracking Working Cache reconciliation belongs only to Tracking Workers.
- Both roles use shared Core data access, numeric calculation, supervisor,
  checkpoint, and Publication modules. Pool separation is scheduling and
  capacity isolation, not duplicated business logic.

### Tracking Advance and Attempt recovery

- Tracking Head and immutable Tracking Checkpoints are the sole authoritative
  recovery state for DailyTrack. Working Cache remains disposable.
- Advance creation uses the then-current Data Generation and declared Tracking
  Worker Capacity to freeze the exact contiguous oldest unpublished Target.
- The planner selects the largest Target from 1 through 63 sessions that fits
  the 75-percent execution-memory budget and is estimated to finish within 30
  seconds. The time value is a sizing target, not a rejection limit.
- If one session fits memory but exceeds the time target, the Advance freezes
  that one session. If the oldest one session cannot fit, the system still
  creates a blocked one-session Advance but creates no Attempt.
- Target coordinates never expand or shrink. New Dataset Head sessions are
  handled by later Advances after the current Advance succeeds.
- A Tracking Attempt is created only when a Tracking Worker claims eligible
  execution. The supervisor starts exactly one child for that Attempt.
- Each Attempt resolves and pins the current Data Generation once. That
  Generation must contain the frozen predecessor and exact ordered Target, and
  it remains fixed for the complete Attempt.
- The child computes the whole Target from the authoritative predecessor and
  returns one bounded all-or-nothing result. The supervisor alone may validate,
  publish the Tracking Checkpoint, and atomically move the Tracking Head.
- Failure, recovered ownership loss, or confirmed Stop discards all unpublished
  output, releases the Attempt-scoped Pin after child exit, and leaves the Head
  unchanged. Tracking creates no cross-Attempt private Execution Checkpoint.
- A later Attempt on the same Advance resolves the then-current Generation and
  recomputes the complete frozen Target from the unchanged Head. It may produce
  changed unpublished values after a Canonical Data correction but cannot
  rewrite published history or mix Generations inside one Checkpoint.
- Generation calendar or predecessor mismatch is a permanent integrity failure,
  not permission to rewrite the Target.

### Tracking cycles, fairness, and explicit recovery

- One Tracking Attempt Cycle contains an initial Attempt plus at most two
  automatic Attempts.
- Only unexpected Worker loss and transient PostgreSQL, RustFS, network,
  timeout, or Publication unavailability are automatically retryable. The
  second Attempt becomes eligible after five seconds and the third after 30
  seconds.
- Canonical Data, calculation, domain, accepted-capacity, integrity,
  equivalence, and other permanent failures block immediately. Exhausting a
  transient Cycle also blocks.
- Only explicit user Retry can reactivate the same persistent Advance. It first
  reevaluates the frozen Target against current Tracking Worker Capacity.
- If the Target still cannot fit, the Track remains blocked without a new Cycle
  or Attempt. If it fits, Retry starts a new bounded Cycle on the same Target.
- Dataset Head movement, capacity changes, container restart, and service
  restart do not automatically reactivate blocked work.
- Tracking Workers rotate eligible DailyTracks fairly. A Track receives at most
  one Attempt before other eligible Tracks, and a still-lagging successful Track
  returns to the tail for its next Advance.
- A transiently failed Track releases the slot during retry delay and returns to
  the queue tail when eligible. Claim fencing prevents concurrent Advances for
  the same Track.
- Tracking Progress exposes authoritative Head and lag, frozen Target, current
  Cycle position, retry-wait state, transient phase, and current session. Only
  atomic publication marks sessions complete.

### DailyTrack Stop and cache lifecycle

- DailyTrack lifecycle includes `active`, `blocked`, `stopping`, and `stopped`.
  `stopping` is non-terminal and continues to count toward the limit of ten
  non-stopped Tracks.
- Stopping a Track with a running Attempt atomically moves the Track, Advance,
  and Attempt to `stopping`, advances the fence, and signals the Tracking Worker
  supervisor.
- While the supervisor remains alive, cooperative shutdown and forced child
  termination share the same five-second confirmed-exit policy as Research
  cancellation.
- Track `stopped`, Attempt and Advance `cancelled`, and Pin release occur only
  after child exit. Lost-supervisor recovery waits for proof that old ownership
  cannot remain live.
- Stopping an active Track with no running Attempt or a blocked Track completes
  immediately in one transaction that cancels the unresolved Advance, current
  Cycle, retry eligibility, and pending claim.
- Stop is irreversible and never creates another Attempt. A stopping Track
  cannot Retry, Delete, or Advance.
- Reaching `stopped` deletes the disposable Working Cache. Authoritative
  Tracking Head and Checkpoints remain until explicit DailyTrack Deletion.
- The existing active-capacity rule counts `active`, `blocked`, and `stopping`
  Tracks and excludes only `stopped` Tracks.

### Public contracts and observability

- Public ResearchRun reads expose queued, running, cancelling, succeeded,
  failed, and cancelled lifecycle states plus committed progress and bounded
  transient liveness. Private checkpoint and staged-publication identifiers are
  not exposed as Results.
- Public DailyTrack reads expose active, blocked, stopping, and stopped state,
  authoritative Head and lag, current Target, Cycle and retry state, and safe
  user-facing failure information.
- Cancel, Retry, and Stop remain explicit idempotent commands. Repeated request
  identifiers replay the same outcome, and conflicting reuse is rejected.
- Logs are structured around Worker role, Run or Track identity, Advance,
  Attempt and Cycle ordinal, Chunk or Target boundary, Data Generation identity,
  committed progress, retry eligibility, termination timing, and closed failure
  category. Secrets and large calculation payloads are excluded.

### Performance acceptance

- The Reference Long Research Workload is
  `cs_rank(pct_change(close_adj, 20))` over the Top 3000 Liquidity Universe from
  2010-01-04 through 2026-08-13 against one frozen representative Data
  Generation.
- It exercises admission and planning, selective columnar reads, Alpha,
  1-, 5-, and 20-session Factor Evaluation, Strategy Backtest, private Chunk
  Checkpoints, finalization, and atomic Result publication.
- The final Production Image runs the workload in one 2-vCPU, 2-GiB single-slot
  Research Worker for five cold and five warm measured samples.
- Queue wait is excluded. Execution begins at successful claim and ends only
  after final Result publication commits.
- Cold execution P95 must be no more than ten minutes, warm execution P95 no
  more than five minutes, peak process RSS no more than 1.5 GiB, first durable
  Checkpoint no later than 45 seconds after `running`, and healthy-supervisor
  cancellation no more than five seconds.
- The fixed dates are a reproducible regression fixture, not the maximum
  supported product date. Telemetry records later workload growth, and these
  thresholds are implementation gates rather than a per-user SLA.

## Testing Decisions

- Tests assert public behavior and durable business invariants, not private
  helper functions, internal call counts, or an incidental class layout.
- The primary seam extends the existing isolated integration and acceptance
  runtime. Scenarios enter through public HTTP, use real PostgreSQL and RustFS,
  and run actual fixed-role Worker supervisors and execution child subprocesses.
  Direct persistence inspection is limited to proving atomic publication,
  fencing, lease, Pin, Checkpoint-chain, and cleanup invariants that cannot be
  established from a public response alone.
- Existing Current Head Research execution, Worker-loss retry, stale-owner
  fencing, cancellation, DailyTrack progression, and database-restart
  acceptance tests are the prior art for this primary seam.
- Primary Research scenarios cover successful multi-Chunk execution, warm-up
  boundaries, financial and market Formulae, frozen Data Generation, committed
  progress, exact one-Result publication, Worker loss after several committed
  Chunks, retry resume, stale child fencing, publication retry, bounded Attempt
  exhaustion, capacity failure, integrity failure, queued cancel, running
  cancel, lost-supervisor recovery, and checkpoint garbage collection.
- Primary Tracking scenarios cover Target planning at 1 and 63 boundaries,
  one-session capacity blocking without an Attempt, all-or-nothing Head movement,
  failure discard, current-Generation retry of the same Target, calendar
  mismatch, transient delays, three-Attempt Cycle exhaustion, explicit Retry,
  no automatic unblock, fair rotation, concurrent claim fencing, stopping with
  and without a child, lost-supervisor Stop recovery, Working Cache deletion,
  and the ten-Track limit under concurrent activation.
- Owned infrastructure is not mocked. Faults are injected at stable external
  boundaries using PostgreSQL barriers, process signals and exits, expired
  leases, publication unavailability, controlled object-store failures, and
  cgroup or capacity declarations.
- Tests never use arbitrary sleeps. They use bounded condition polling or
  explicit synchronization and print current process state, claims, leases,
  fences, progress, logs, and publication evidence on timeout.
- Deterministic Kernel contract tests are the narrow seam for pure planning and
  numerical rules. They compare uninterrupted and Chunked execution by canonical
  bytes across nulls, Universe changes, cross-sectional ranks, rolling windows,
  financial fields, Factor state, Strategy state, staged observation assembly,
  and final Result serialization.
- Planner contract tests fix Formula work, required fields, Universe cardinality,
  Worker capacity, time estimates, dates, and sessions. They cover the largest
  safe 1-to-63 selection, time-target exceedance, one-session memory rejection,
  frozen planning across retry, and refusal to silently replan after capacity
  reduction.
- Small browser E2E coverage verifies only user-visible workflow: long Run
  admission, committed versus in-flight progress, cancelling, failure reason,
  DailyTrack Target and retry waiting, explicit Retry, stopping, and terminal
  state. Browser tests do not reproduce numeric or process-failure matrices.
- Production Image smoke verifies role-specific startup, one-slot topology,
  declared cgroup capacity checks, API and web readiness, offline use of mounted
  Canonical Data, Research execution, Tracking execution, restart durability,
  and absence of obsolete mixed-role or alternate-engine paths.
- The Release benchmark runs the exact Reference Long Research Workload through
  the final Production Image. It records five cold and five warm samples,
  duration, P95, peak RSS, first Checkpoint latency, cancellation confirmation,
  data object and byte reads, Chunk plan, and image revision, then enforces the
  accepted thresholds.
- Every test environment uses a fresh isolated Compose project, database,
  bucket, network, volumes, accounts, fixed time and timezone, stable UUID and
  random seeds, and replay or fixture Canonical Data. No automated test depends
  on public Tushare or test execution order.
- Failure artifacts include structured Worker and child logs, exit codes,
  process identity, cgroup limits, API responses, Run and Track state, Attempt
  and Cycle history, Checkpoint and Publication manifests, fence and lease facts,
  timing samples, and image version.
- The ordinary implementation gate runs fast Kernel and architecture checks,
  real integration and acceptance tests, and browser E2E. The release gate adds
  Production Image smoke and the long-workload benchmark.

## Out of Scope

- New Alpha fields, builtins, Formula syntax, Strategy types, or user-authored
  execution plugins.
- Tushare collection, Market or Financial source repair, Canonical Data
  bootstrap, and Data Generation publication behavior except where a frozen
  fixture is needed to exercise execution.
- A Polars, DuckDB, SQL, GPU, distributed-compute, or versioned alternative
  Research engine.
- Instrument sharding, cross-Worker Chunk distribution, in-process concurrent
  Runs, dynamic work stealing inside one Run, or changing numerical association
  to gain speed.
- Shortest-job-first scheduling, user priorities, separate short and long
  Research queues, per-user Worker sizing, or per-Run CPU and memory controls.
- Temporal, Redis, an event bus, outbox relay, generic job table, generic
  scheduler, or third Maintenance Worker role.
- User-visible private Checkpoints, partial Alpha or Factor output, provisional
  Strategy metrics, or partial Result downloads.
- Private Tracking execution checkpoints, cross-Attempt Tracking continuation,
  Tracking Generation branches, or automatic replay of published Tracking
  history after a data correction.
- Automatic reactivation of blocked DailyTracks after Dataset Head movement,
  capacity changes, deployment, or restart.
- Product State migration, backward compatibility, fallback readers, old
  Numeric Execution Contract dispatch, or downgrade support.
- Hosted deployment, autoscaling policy, authentication, tenants, quotas,
  billing, collaboration, or a customer-facing performance SLA.
- Changing the existing maximum of ten non-stopped DailyTracks.
- Redesigning Research authoring, Research Folders, Result presentation, or
  DailyTrack deletion beyond the progress and lifecycle states required here.

## Further Notes

- The accepted architecture decisions describe the target state. The current
  runtime still contains total-work admission rejection, a mixed Worker loop,
  whole-period Python materialization, and coarser Research and Tracking
  recovery. Implementation must remove those obsolete paths rather than layer
  the target beside them.
- Research and DailyTrack intentionally have different recovery economics.
  Historical Research is expensive and resumes from private Chunk Checkpoints;
  incremental Tracking is bounded and recomputes from its authoritative Head.
  This is one shared engine with two recovery policies, not duplicated
  execution implementations.
- Attempt, Chunk, Advance, Cycle, ResearchRun, and DailyTrack are distinct
  lifecycle boundaries and must remain named consistently in schema, API,
  logging, UI, and tests.
- The fixed benchmark ending on 2026-08-13 exists only for reproducibility.
  Product support remains 2010 through the latest covered Research Session.
- This Spec is ready to be decomposed into implementation issues. Each issue
  should preserve an end-to-end working product boundary and remove the
  superseded path in the same change rather than leaving compatibility branches.

## Comments
