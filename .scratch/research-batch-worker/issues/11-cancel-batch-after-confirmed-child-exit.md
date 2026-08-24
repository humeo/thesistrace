# 11 — Cancel a Research Batch after confirmed child exit

**What to build:** Let an API client idempotently cancel one complete queued or
running Research Batch, fencing further publication immediately, preserving
completed Results, and reaching terminal cancelled only after the active child
has definitely exited and incomplete state is cleaned.

**Blocked by:** 09 — Recover Strategy Sweeps through a private shared artifact

**Status:** complete

## Implementation plan

1. Add the hard-cut whole-Batch cancellation command, receipt schema, HTTP
   contract, lifecycle conflict rules, and atomic queued cancellation path.
2. Make running cancellation advance the Batch fence first, then let the owning
   Batch Worker supervise a cooperative child cancel with a bounded forced-exit
   fallback; never signal a Worker PID from the API process.
3. After control-lock-confirmed child exit, atomically cancel only unfinished
   child Runs/Items, close the active Attempt, release its Generation Pin,
   discard incomplete task/live state and Attempt files, and release any private
   shared artifact while preserving acknowledged Results and DailyTracks.
4. Reconcile cancelling state after Worker/API/dependency loss and prove the
   deterministic natural-completion versus cancellation race and stale-fence
   publication boundary.
5. Add real PostgreSQL/RustFS/process acceptance for queued, cooperative,
   forced, retry/loss/restart, replay/conflict, retention, cleanup, and races;
   run full gates, close independent Standards/Spec review findings, and commit
   the ticket separately.

- [x] The backend exposes one whole-Batch cancellation command with its own idempotent request ID and no per-item cancellation route.
- [x] Exact cancellation replay returns the same receipt and terminal meaning; reuse of the request ID for a different Batch or command returns a conflict.
- [x] Cancelling a queued Batch prevents every future claim and marks all unfinished child Runs cancelled without starting an execution child.
- [x] Cancelling a running Batch records cancelling and advances the execution fence before asking the active child to stop, so no later stale output can publish.
- [x] A healthy child receives up to five seconds to exit cooperatively and is terminated if it does not; terminal cancelled is recorded only after exit is confirmed.
- [x] The active Data Generation Pin is released only after confirmed child exit and terminal durable cleanup.
- [x] Already acknowledged task outcomes and already-published Results remain authoritative and available after cancellation.
- [x] Every unfinished child Run becomes cancelled, while failed and succeeded sibling outcomes are retained without rollback or reinterpretation.
- [x] Any DailyTrack independently seeded from a completed Strategy child remains intact.
- [x] Cancellation removes live heartbeat, unchecked output, incomplete Checkpoints, inactive Attempt files, and now-unused private shared-artifact references through the durable cleanup path.
- [x] Cancellation during retry wait, supervisor loss, API restart, object-store outage, and stale-child publication still converges to one fenced terminal outcome without leaking resumable work.
- [x] A cancellation racing final acknowledgement has one deterministic winner: completed natural terminal state wins if it committed first; otherwise cancellation prevents the late acknowledgement.
- [x] Late cancellation of an already naturally terminal Batch cannot rewrite succeeded, completed_with_failures, or failed into cancelled.
- [x] A cancelled Batch is terminal and can never resume; rerunning unfinished inputs requires a new admission.
- [x] Cancellation never deletes the Batch, completed child Runs, Results, or Batch history.
- [x] Real process acceptance covers queued cancellation, cooperative exit, forced exit within the five-second budget, retry wait, lost supervisor, stale child, race resolution, exact replay, conflict, cleanup, and restart without arbitrary sleeps.

## Comments

- Parent: Research Batch Worker.
- Cancellation stops remaining calculation; it deliberately preserves work already completed and published.
- Focused real-dependency run `20260824t105818z-64291-89ea9563` passed eight
  main cancellation cases, one PostgreSQL restart case, and one RustFS restart
  case. The fast Python regression passed 569 tests.
- Independent final Standards and Spec reviews both passed with zero P0, P1,
  or P2 findings after the starting-claim, fail-closed database, durable task
  Attempt, and stale-publication fixes.
