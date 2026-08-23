# 08 — Recover complete Factor tasks with bounded retry

**What to build:** Let a Factor Evaluation Batch survive child or Worker loss by
starting a new supervised Attempt at the first incomplete whole Alpha-and-Factor
task, never recomputing acknowledged items and never treating internal Chunks as
durable Batch progress.

**Blocked by:** 06 — Report truthful Batch history, outcomes, and progress; 07 — Isolate and scale FIFO Batch Research claims

**Status:** ready-for-agent

- [ ] One Research Batch Attempt starts exactly one supervised execution child for the Attempt's complete lifetime; loss of either ends that Attempt and every new Attempt starts a new child.
- [ ] The execution child receives immutable calculation input and Attempt-scoped output authority but has no PostgreSQL credentials or RustFS publication authority.
- [ ] The supervisor exclusively owns claims, leases, heartbeats, fences, Generation protection, output validation, task acknowledgement, and Result publication.
- [ ] A Factor task becomes durably complete only after its whole Alpha-and-Factor output is validated, its ordinary Result is published, and its completion is acknowledged under the current fence.
- [ ] Recovery resumes at the first incomplete submitted Factor and never recalculates or republishes an acknowledged Factor task.
- [ ] Work interrupted before acknowledgement restarts the complete Alpha-and-Factor task; internal bounded Chunks remain memory and cancellation details rather than public or durable Batch checkpoints.
- [ ] A transient infrastructure failure receives at most three total attempts for the affected complete task across Batch Attempts.
- [ ] Permanent input, capacity, contract, integrity, and deterministic calculation failures receive no retry.
- [ ] Retry exhaustion fails only the affected Factor Run and allows later independent Factor items to continue.
- [ ] Worker loss before task acknowledgement, child loss, lease expiry, transient database failure, transient object-store failure, and restart all preserve one authoritative owner and reject stale publication.
- [ ] Failure after acknowledged publication cannot create a duplicate Result, duplicate task completion, or recomputation on the next Attempt.
- [ ] Every Attempt remains bound to the originally admitted Data Generation even when Refresh advances the Dataset Head during execution or retry.
- [ ] Generation retention and the active Attempt Pin prevent collection of the frozen Generation until the child is confirmed exited and terminal durable state is recorded.
- [ ] A new Attempt may reset live progress for its incomplete Factor while completed Factor counts, prior outcomes, retry counts, and ordered IDs remain stable.
- [ ] Terminal success, failure, and retry exhaustion clean unchecked output and inactive Attempt state without deleting authoritative Results or recovery evidence.
- [ ] Real process and dependency tests kill the Worker and child independently and prove recovery, retry limits, fences, Generation safety, and cleanup without arbitrary sleeps.

## Comments

- Parent: Research Batch Worker.
- Recovery granularity is deliberately one complete Alpha-and-Factor task, never one internal calculation Chunk.
