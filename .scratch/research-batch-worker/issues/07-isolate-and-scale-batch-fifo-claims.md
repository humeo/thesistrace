# 07 — Isolate and scale FIFO Batch Research claims

**What to build:** Make ordinary Research, Batch Research, and Tracking three
fixed, disjoint Worker roles, and let multiple Batch Worker replicas start
different whole Batches in deterministic FIFO claim order without splitting or
preempting one Batch.

**Blocked by:** 04 — Execute Factor Evaluation Batches with shared preparation

**Status:** ready-for-agent

- [ ] The one Worker executable and Production Image support exactly three mutually exclusive startup roles: research, batch-research, and tracking.
- [ ] The selected role is frozen at startup, owns one execution slot, and never falls back to another role's work when its own claim set is empty.
- [ ] Research Workers claim only non-Batch ResearchRuns, Batch Research Workers claim only Research Batches, and Tracking Workers claim only Tracking Advances.
- [ ] A Batch-owned ResearchRun is never independently claimable, including after Worker restart, lease expiry, or item failure.
- [ ] Claiming orders eligible Batches by admission time and then Batch ID, and real concurrent claims cannot give the same Batch to two active owners.
- [ ] Multiple Batch Worker replicas claim distinct next Batches in FIFO start order while an earlier claimed Batch remains active.
- [ ] FIFO promises claim and start order, not completion order; a shorter later Batch may finish first on another replica.
- [ ] One Batch Worker owns one whole Batch for its Attempt and processes items serially in submitted order.
- [ ] One Batch is never divided among replicas, internally parallelized, reprioritized, reordered, or preempted.
- [ ] Ordinary interactive Research execution remains claimable by its dedicated Worker while long Batch work is queued or running.
- [ ] Startup rejects unknown roles and invalid slot configuration instead of silently selecting a default role or shared queue.
- [ ] Real database contention tests hold the first claim at an execution barrier and prove distinct FIFO claims using bounded condition polling rather than sleeps.
- [ ] Worker events identify role, Batch, claim order, ownership, Attempt, and exit sufficiently to diagnose scheduling without exposing sensitive input.
- [ ] No priority system, fairness class, deadline scheduler, external queue, event bus, or interchangeable Research/Batch claim path is introduced.

## Comments

- Parent: Research Batch Worker.
- This ticket can proceed alongside Strategy-specific work after the first Factor Batch slice is green.
