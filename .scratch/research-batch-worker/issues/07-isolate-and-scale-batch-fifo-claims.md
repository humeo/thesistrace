# 07 — Isolate and scale FIFO Batch Research claims

**What to build:** Make ordinary Research, Batch Research, and Tracking three
fixed, disjoint Worker roles, and let multiple Batch Worker replicas start
different whole Batches in deterministic FIFO claim order without splitting or
preempting one Batch.

**Blocked by:** 04 — Execute Factor Evaluation Batches with shared preparation

**Status:** completed

## Implementation plan

1. Preserve the existing one executable/one image/three fixed-role dispatch,
   and enrich Worker lifecycle events with the frozen role, slot, Batch FIFO
   key, Attempt ownership, and clean `--once` exit.
2. Serialize only the short Batch claim transaction, then select the oldest
   queued Batch by `(created_at, id)` with `FOR UPDATE SKIP LOCKED`; keep the
   complete ordered child set under that one Attempt and release the claim
   transaction before calculation.
3. Add real multi-process PostgreSQL barriers that keep the oldest Batch active
   while later replicas claim distinct next Batches, prove a later Batch may
   finish first, and prove an ordinary Research Worker remains independent.
4. Verify unknown or multi-slot startup fails closed, Batch-owned Runs never
   enter ordinary Research claims, and emitted claim/child/exit identities are
   sufficient to reconstruct ownership without exposing inputs.
5. Run focused, fast, isolated integration, and Production Image topology
   checks; then complete independent Standards and Spec reviews before the
   Ticket 07 commit.

- [x] The one Worker executable and Production Image support exactly three mutually exclusive startup roles: research, batch-research, and tracking.
- [x] The selected role is frozen at startup, owns one execution slot, and never falls back to another role's work when its own claim set is empty.
- [x] Research Workers claim only non-Batch ResearchRuns, Batch Research Workers claim only Research Batches, and Tracking Workers claim only Tracking Advances.
- [x] A Batch-owned ResearchRun is never independently claimable, including after Worker restart, lease expiry, or item failure.
- [x] Claiming orders eligible Batches by admission time and then Batch ID, and real concurrent claims cannot give the same Batch to two active owners.
- [x] Multiple Batch Worker replicas claim distinct next Batches in FIFO start order while an earlier claimed Batch remains active.
- [x] FIFO promises claim and start order, not completion order; a shorter later Batch may finish first on another replica.
- [x] One Batch Worker owns one whole Batch for its Attempt and processes items serially in submitted order.
- [x] One Batch is never divided among replicas, internally parallelized, reprioritized, reordered, or preempted.
- [x] Ordinary interactive Research execution remains claimable by its dedicated Worker while long Batch work is queued or running.
- [x] Startup rejects unknown roles and invalid slot configuration instead of silently selecting a default role or shared queue.
- [x] Real database contention tests hold the first claim at an execution barrier and prove distinct FIFO claims using bounded condition polling rather than sleeps.
- [x] Worker events identify role, Batch, claim order, ownership, Attempt, and exit sufficiently to diagnose scheduling without exposing sensitive input.
- [x] No priority system, fairness class, deadline scheduler, external queue, event bus, or interchangeable Research/Batch claim path is introduced.

## Comments

- Parent: Research Batch Worker.
- This ticket can proceed alongside Strategy-specific work after the first Factor Batch slice is green.
- Standards review: PASS, P0/P1/P2 = 0/0/0 after re-review. The final harness
  captures return code, stdout, and stderr on every barrier failure and uses a
  bounded terminate-then-kill cleanup path.
- Spec review: PASS, P0/P1/P2 = 0/0/0 after re-review. Three real Worker
  processes claimed distinct Batches in `(created_at, id)` order while the
  oldest remained active; a later Batch completed first without blocking an
  ordinary Research Worker.
- Fast gate: Ruff passed and 560 tests passed. The same-image three-role Compose
  topology checks passed with the architecture suite.
- Isolated PostgreSQL/RustFS integration run
  `20260824t022117z-5576-1a58dc64`: 218 passed, then the database-restart
  acceptance passed; isolated containers, network, and data volumes were
  cleaned up.
