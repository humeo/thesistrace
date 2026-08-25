# 03 — Admit and inspect Research Batches atomically

**What to build:** Let an API client atomically submit either an ordered Factor
Evaluation Batch or an ordered single-Alpha Strategy Sweep and immediately
inspect the durable Batch and its stable child ResearchRun identities, without
adding a Batch frontend.

**Blocked by:** None — can start immediately

**Status:** complete

## Plan

1. Add contract and architecture tests for the two discriminated admission
   shapes, one-to-twenty bounds, ordered unique item keys, canonical duplicate
   rejection, item-aware compiler diagnostics, cursor list/detail responses,
   protected Batch Research Folder, and absence of Batch DELETE/UI surfaces.
2. Introduce one `research_batch` domain module owning API models, schema,
   admission fingerprints, ordered Batch/Item persistence, initial progress,
   idempotent receipts, and read projections; register it as a new Core schema
   and runtime service without adding an execution path.
3. Add narrow ResearchRun-owned preparation and transaction-aware child
   admission seams. Batch admission compiles and validates every child against
   one frozen Dataset snapshot, evaluates the complete sequential capacity
   envelope, then atomically inserts Batch state, child Runs/progress, one
   Generation retention, Items, and receipt.
4. Mark child Runs with an explicit Batch execution owner and update the
   ordinary Research Worker claim to select ordinary ownership only. Ensure the
   stable `folder_batch_research` Folder at schema initialization and protect it
   from deletion while keeping ordinary organization behavior.
5. Cover exact replay, request conflict, concurrent duplicate admission,
   injected transaction failure, restart, invalid/oversized requests, no
   partial rows/retentions/publications, stable child IDs, and frozen scope in
   real PostgreSQL/RustFS acceptance.
6. Run focused and complete gates, perform independent Standards and Spec
   review, fix and re-review to clean, update this tracker, and create the
   independent Ticket 03 commit.

- [x] The public admission contract requires an explicit Research Batch Kind and accepts only factor_evaluation or strategy_sweep.
- [x] Factor Evaluation admission accepts one through twenty ordered Factor items and rejects Strategy fields, empty input, and a twenty-first item.
- [x] Strategy Sweep admission accepts exactly one shared Alpha plus one through twenty ordered Strategy parameter items; the shared Alpha does not consume the item limit and no Alpha-by-Strategy cross-product is inferred.
- [x] One Batch freezes its Research Period, Liquidity Universe, Industry Neutralization choice, Numeric Execution Contract, Data Generation, and relevant semantic versions for every child Run.
- [x] Every item requires a unique item_key, preserves its submitted ordinal, and receives a stable ordinary ResearchRun ID during admission.
- [x] Every Formula is compiled and every common and per-item field is validated before admission commits; diagnostics identify the failing item_key and field and retain source-range information for Formula errors.
- [x] Canonically equivalent Factor Expressions are rejected as duplicates with both conflicting item_key values, regardless of names, whitespace, or formatting.
- [x] Duplicate Strategy parameter tuples are rejected with both conflicting item_key values.
- [x] Admission capacity is evaluated for the complete Batch against the declared execution envelope before any Product State is created.
- [x] The Batch, ordered Batch Items, admission receipt, Generation retention, and all child ResearchRuns commit atomically or none of them exist.
- [x] Exact idempotent replay returns the same Batch and ordered child IDs; reuse of the request ID with different canonical input returns a conflict.
- [x] Concurrent duplicate admission, transaction failure, restart after an uncertain response, and invalid or oversized requests cannot create duplicate or partial Batches, Runs, receipts, retentions, or Publication objects.
- [x] Child Runs are initially placed in the stable Batch Research Folder but immutable Batch membership is recorded independently of Folder membership.
- [x] A Batch owns orchestration and ordered membership but owns no combined Result; each child Run retains its ordinary immutable input and future Result ownership.
- [x] Batch-owned ResearchRuns are structurally ineligible for ordinary Research Worker claiming from the moment admission commits.
- [x] Cursor listing and detail can return the newly admitted queued Batch with its frozen scope and ordered item-to-Run mapping; child Results are not embedded.
- [x] No Batch DELETE route, compatibility payload, mixed-kind Batch, legacy alias, migration reader, fallback queue, or frontend Batch surface is introduced.

## Comments

- Parent: Research Batch Worker.
- This is the durable backend admission slice; execution begins in later tickets without a temporary executor.
- Final Standards review: PASS, P0/P1/P2 = 0/0/0.
- Final Spec review: PASS, P0/P1/P2 = 0/0/0.
- Fast gate: Ruff plus 545 Kernel/Architecture/Adapter/Data tests passed.
- Isolated PostgreSQL/RustFS gate: run `20260823t210716z-12972-383f647b`,
  199 integration/acceptance tests passed and one database-restart test passed;
  cleanup completed.
