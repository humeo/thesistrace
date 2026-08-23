---
status: accepted
---

# Make Research Batch a durable orchestration resource

A Research Batch is a durable backend-only resource that atomically admits
ordinary ResearchRuns sharing one Research Folder, Research Period, Liquidity
Universe, Industry Neutralization choice, and Data Generation. The Research
Batch owns orchestration and aggregate lifecycle but never a Result Bundle;
every accepted item has a stable ResearchRun identity and its own immutable
Result, while invalid admission creates neither the Research Batch nor any Run.

V1 has exactly two explicit Research Batch Kinds. `factor_evaluation` accepts an
ordered list of independent Factor Evaluation inputs and creates one
`factor_evaluation` ResearchRun per Alpha. `strategy_sweep` accepts exactly one
Alpha and an ordered list of parameter combinations for the one current
Strategy, creating one `strategy_backtest` ResearchRun per combination. There
is no mixed Batch, implicit cross-product, multiple-Alpha Strategy, or alternate
Strategy algorithm. Every calculation Result must remain exactly identical under
the existing semantic-result checksum to the equivalent individually admitted
ResearchRun, while each Result provenance binds to its own ResearchRun identity.

Each Batch contains from one through twenty submitted items. For
`factor_evaluation`, this limit applies to `factors`; for `strategy_sweep`, it
applies to `strategies`, and the one shared Alpha does not consume another item.
The fixed item limit does not bypass the existing per-Alpha admission rules or
the fail-closed capacity check for the complete shared execution footprint.

Admission rejects duplicate computation items instead of silently running or
deduplicating them. In a Factor Evaluation Batch, equality is the canonical
compiled Alpha Expression, independent of formatting, Research Name, or
Investment Hypothesis. In a Strategy Sweep, equality is the current Strategy's
complete `(holdings_count, rebalance_every_sessions)` parameter tuple. A
duplicate diagnostic identifies both conflicting `item_key` values.

Research Batch is distinct from Batch-Incremental Equivalence. Keeping its API
backend-only is a presentation boundary, not permission to make its lifecycle
ephemeral.

The backend API consists of `POST /api/research-batches`, cursor-paginated
`GET /api/research-batches`, `GET /api/research-batches/{batch_id}`, and
`POST /api/research-batches/{batch_id}/cancel`. Admission returns `202` with the
Batch summary and the ordered `item_key` to ResearchRun ID mapping. Detail owns
aggregate state, two-layer progress, Attempt information, and ordered item
outcomes while each Run and Result remains available through the ordinary
ResearchRun API. Cancellation carries its own request ID and is idempotent.
Admission rejection returns item-scoped `422` issues; reuse of one request ID
with a different canonical request returns `409`. V1 exposes no per-item Batch
retry or cancellation endpoint.

V1 exposes no Research Batch deletion endpoint. A Batch-owned ResearchRun keeps
the ordinary terminal-only `DELETE /api/research-runs/{run_id}` operation shown
on its existing detail page. The Batch Item remains as orchestration history
with its original ResearchRun ID, final outcome, and deletion timestamp, while
the deleted Run and any unreferenced Result are no longer available. Deleting
one Run never deletes the Batch, another Run, or an independently activated
DailyTrack.

Every Batch-owned ResearchRun is initially organized in the system-created Batch
Research Folder and remains visible through the existing Research list and
detail surfaces. Batch identity comes from immutable Batch membership rather
than `folder_id`; ordinary rename, move, Browser Draft, and Run organization
semantics remain available, while the stable default Folder itself cannot be
deleted. V1 adds no Batch authoring, status, or control surface to the frontend.

In a Factor Evaluation Batch, permanent failure of one Alpha fails only its Run
and the remaining Alphas continue. In a Strategy Sweep, permanent failure of the
one shared Alpha fails every dependent Run, while failure of one Strategy fails
only that parameter combination. Successful Results are never rolled back
because another item failed.

Research Batch detail exposes two progress layers. Durable progress reports
completed whole tasks: completed Factor Evaluations for a Factor Batch, or the
shared Alpha-and-Factor status plus completed Strategies for a Strategy Sweep.
Live progress additionally reports the current `item_key`, execution phase,
completed and total Research Sessions when applicable, estimated percentage,
elapsed time, and Attempt number. This live estimate may reset when an
incomplete task is retried; it is not a partial Result or a finer recovery
checkpoint. Clients must display the durable count separately from the live
estimate instead of presenting the estimate as committed work.

Natural execution ends `succeeded` when every Run succeeds,
`completed_with_failures` when successful and failed Runs coexist, and `failed`
when no Run succeeds. V1 cancellation applies only to the complete Research
Batch: an individual Batch-owned Run cannot be cancelled independently,
already-published Results remain immutable, and not-yet-completed Runs become
cancelled. A running cancellation first records `cancelling` and advances the
Batch fence, gives the execution child up to five seconds to stop cooperatively,
then terminates it if necessary. Data Generation protection is released only
after the child has exited and the Batch is durably `cancelled`. A successful
Batch-owned Strategy Backtest retains the ordinary ability to seed an
independent DailyTrack.

Cancellation is prospective rather than a rollback. The durable Batch record,
final item outcomes, sanitized diagnostics, and Results published by already
succeeded Runs remain available. The incomplete task's live heartbeat,
unchecked output, Checkpoints, Attempt files, and any now-unneeded private
shared artifact become collectible after confirmed child exit. A cancelled
Batch cannot resume; executing the unfinished inputs requires a new admission.
