# 05 — Execute Strategy Sweeps from one shared Alpha and Factor

**What to build:** Let the dedicated Batch Research Worker calculate one
Strategy Sweep's Data, Alpha, and Factor work once and then execute each ordered
Strategy parameter combination as an independent ordinary Strategy Backtest.

**Blocked by:** 02 — Recompose Strategy execution from the shared outcome; 04 — Execute Factor Evaluation Batches with shared preparation

**Status:** completed

## Implementation plan

1. Generalize the dedicated Batch claim and supervised child request to carry
   either admitted Batch Kind while preserving one fixed Worker role, one child,
   and oldest-claimable Batch ownership.
2. For a Strategy Sweep, read the frozen canonical Data slice and prepare the
   Universe and Forward Labels once, then execute the formal Alpha-and-Factor
   seam once across its bounded chunks and retain only the validated in-process
   outcomes for this Attempt.
3. After the complete shared prerequisite is acknowledged, execute each
   Strategy item in submitted ordinal order through
   `execute_strategy_chunk_from_alpha_factor_outcome`, keeping independent
   Strategy continuation and observations per child Run.
4. Add a ResearchRun-owned atomic Strategy Result publication seam that accepts
   the complete validated Batch task output, publishes the ordinary self-
   contained Result, and preserves each child identity/provenance and normal
   DailyTrack eligibility.
5. Verify shared-stage evidence, exact ordinary-Run semantic equivalence,
   shared-prerequisite and per-Strategy failure scope, all/mixed/no-success
   aggregate outcomes, 1/20 ordering, memory, and Production Image execution;
   then complete independent Standards and Spec reviews before the Ticket 05
   commit.

- [x] A Strategy Sweep prepares its frozen Data once and completes exactly one shared Alpha-and-Factor task before any dependent Strategy task runs.
- [x] The current Strategy calculation runs exactly once per submitted parameter tuple and in submitted ordinal order.
- [x] No implicit Cartesian product, second Alpha, alternate Strategy algorithm, or server-generated parameter combination is accepted or executed.
- [x] Every successful item publishes an ordinary self-contained Strategy Backtest Result containing the shared Factor Summary, that item's Strategy Summary, Strategy Daily Observations, and Terminal Strategy State.
- [x] Every child Result carries its own correct ResearchRun identity and provenance even though its Factor calculation was shared.
- [x] Against the same frozen Generation, each Batch item has exact Factor, Strategy, and terminal-state semantic checksums, calculation contracts, and semantic versions as the equivalent separately admitted ordinary Strategy Backtest.
- [x] Stage and I/O evidence proves one Data preparation, one Alpha execution, one Factor execution, and one Strategy execution per submitted item.
- [x] A permanent failure of the shared Alpha-and-Factor task fails every dependent Strategy Run without starting Strategy calculation.
- [x] A deterministic failure of one Strategy parameter combination fails only that child Run and allows later Strategy items to continue.
- [x] Successful, failed, and mixed outcomes derive the correct Batch aggregate state without creating a combined Batch Result or selecting a best parameter tuple.
- [x] A successful child Strategy Run retains the ordinary ability to seed a DailyTrack, while Batch execution never starts tracking automatically.
- [x] Strategy parameters cannot mutate the shared Alpha-and-Factor outcome or change the Factor Summary included in sibling Results.
- [x] One-item and twenty-item Strategy Sweeps use the same contract, and the shared Alpha remains outside the item count.
- [x] Peak child RSS remains inside the existing execution budget while shared work is retained for the active Sweep.
- [x] The implementation reuses the formal Research Kernel seam and ordinary Publication contract; it adds no copied math, public shared artifact, permanent Alpha store, cross-Batch cache, second image, or Batch frontend.

## Comments

- Parent: Research Batch Worker.
- Durable cross-Attempt reuse of the shared prerequisite is added after the recovery boundary is established.
- Standards review: PASS, P0/P1/P2 = 0/0/0 after re-review. The fixes model
  the pending-session overlap in every compact shared outcome and release each
  decoded outcome before the next Strategy chunk.
- Spec review: PASS, P0/P1/P2 = 0/0/0 after re-review. The publication fix uses
  ordinary execution-plan partitions, including the 504-session boundary.
- Focused real acceptance: 9 passed, covering exact ordinary Result and
  provenance equivalence, shared and per-item failures, 1/20 ordering,
  505-session partition equivalence, the 300 MiB/512-instrument boundary, and
  the high-work `16 * ts_mean(close, 252)` pending-overlap RSS boundary.
- Fast gate: Ruff passed and 565 tests passed.
- Isolated PostgreSQL/RustFS integration run
  `20260824t002307z-55245-6fcadb4d`: 212 passed, then the database-restart
  acceptance passed; isolated resources were cleaned up.
- Production Image smoke run `20260824t002959z-59546-1ce652e8`: passed the
  real Strategy Sweep, Worker-stage, loss/restart, API, and web checks; all
  containers, networks, and data volumes were cleaned up.
