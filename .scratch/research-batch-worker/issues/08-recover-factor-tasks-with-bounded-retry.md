# 08 — Recover complete Factor tasks with bounded retry

**What to build:** Let a Factor Evaluation Batch survive child or Worker loss by
starting a new supervised Attempt at the first incomplete whole Alpha-and-Factor
task, never recomputing acknowledged items and never treating internal Chunks as
durable Batch progress.

**Blocked by:** 06 — Report truthful Batch history, outcomes, and progress; 07 — Isolate and scale FIFO Batch Research claims

**Status:** complete

## Implementation plan

1. Persist one Factor-task attempt at the first incomplete submitted item for
   each Batch Attempt, with a three-attempt bound and database lifecycle
   invariants. Keep calculation Chunks out of this recovery state.
2. Recover an expired Factor Batch Attempt under the FIFO claim lock: fence and
   close the lost Attempt, release its Generation Pin, reset only incomplete
   child Runs, and start one new supervised child with only the remaining
   ordered items.
3. Classify child/process/database/publication loss as transient task failure;
   retry the whole affected Factor task, but make permanent failures and retry
   exhaustion terminal only for that item so later Factors continue.
4. Add deterministic real-process and real-dependency acceptance tests for
   Worker/child loss, bounded retry, stale fences, stable Generation binding,
   no duplicate publication, monotonic progress, and cleanup.
5. Run focused gates and the full isolated integration runtime, then complete
   independent Standards and Spec reviews and resolve every finding before the
   ticket commit.

- [x] One Research Batch Attempt starts exactly one supervised execution child for the Attempt's complete lifetime; loss of either ends that Attempt and every new Attempt starts a new child.
- [x] The execution child receives immutable calculation input and Attempt-scoped output authority but has no PostgreSQL credentials or RustFS publication authority.
- [x] The supervisor exclusively owns claims, leases, heartbeats, fences, Generation protection, output validation, task acknowledgement, and Result publication.
- [x] A Factor task becomes durably complete only after its whole Alpha-and-Factor output is validated, its ordinary Result is published, and its completion is acknowledged under the current fence.
- [x] Recovery resumes at the first incomplete submitted Factor and never recalculates or republishes an acknowledged Factor task.
- [x] Work interrupted before acknowledgement restarts the complete Alpha-and-Factor task; internal bounded Chunks remain memory and cancellation details rather than public or durable Batch checkpoints.
- [x] A transient infrastructure failure receives at most three total attempts for the affected complete task across Batch Attempts.
- [x] Permanent input, capacity, contract, integrity, and deterministic calculation failures receive no retry.
- [x] Retry exhaustion fails only the affected Factor Run and allows later independent Factor items to continue.
- [x] Worker loss before task acknowledgement, child loss, lease expiry, transient database failure, transient object-store failure, and restart all preserve one authoritative owner and reject stale publication.
- [x] Failure after acknowledged publication cannot create a duplicate Result, duplicate task completion, or recomputation on the next Attempt.
- [x] Every Attempt remains bound to the originally admitted Data Generation even when Refresh advances the Dataset Head during execution or retry.
- [x] Generation retention and the active Attempt Pin prevent collection of the frozen Generation until the child is confirmed exited and terminal durable state is recorded.
- [x] A new Attempt may reset live progress for its incomplete Factor while completed Factor counts, prior outcomes, retry counts, and ordered IDs remain stable.
- [x] Terminal success, failure, and retry exhaustion clean unchecked output and inactive Attempt state without deleting authoritative Results or recovery evidence.
- [x] Real process and dependency tests kill the Worker and child independently and prove recovery, retry limits, fences, Generation safety, and cleanup without arbitrary sleeps.

## Comments

- Parent: Research Batch Worker.
- Recovery granularity is deliberately one complete Alpha-and-Factor task, never one internal calculation Chunk.
- Implementation: child-ready 前使用 `starting_claims` 保留领取与 Generation Pin；子进程持有共享 control-volume flock 并报告 ready 后才原子创建正式 Batch Attempt 和 Factor Task Attempt。恢复只有在取得同一 flock、确认旧 child 已退出后，才关闭 Attempt、释放 Pin 和重排未完成任务。
- Verification: Ruff passed; fast suite `568 passed`; focused Batch suite `22 passed`; full isolated integration run `20260824t045439z-76487-6f76e92f` passed `222` main tests plus ordinary PostgreSQL restart, real RustFS restart, and real Batch PostgreSQL restart phases (`1 passed` each), then removed its containers, network, and volumes.
- Independent Standards re-review: PASS (`P0/P1/P2 = 0/0/0`). The prior real-dependency, implementation-trace assertion, and duplicated transaction findings are closed.
- Independent Spec re-review: PASS (`P0/P1/P2 = 0/0/0`). The prior zero-child Attempt, unconfirmed-child Pin release, and simulated-dependency findings are closed.
