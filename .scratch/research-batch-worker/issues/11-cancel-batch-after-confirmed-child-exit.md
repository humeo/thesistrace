# 11 — Cancel a Research Batch after confirmed child exit

**What to build:** Let an API client idempotently cancel one complete queued or
running Research Batch, fencing further publication immediately, preserving
completed Results, and reaching terminal cancelled only after the active child
has definitely exited and incomplete state is cleaned.

**Blocked by:** 09 — Recover Strategy Sweeps through a private shared artifact

**Status:** ready-for-agent

- [ ] The backend exposes one whole-Batch cancellation command with its own idempotent request ID and no per-item cancellation route.
- [ ] Exact cancellation replay returns the same receipt and terminal meaning; reuse of the request ID for a different Batch or command returns a conflict.
- [ ] Cancelling a queued Batch prevents every future claim and marks all unfinished child Runs cancelled without starting an execution child.
- [ ] Cancelling a running Batch records cancelling and advances the execution fence before asking the active child to stop, so no later stale output can publish.
- [ ] A healthy child receives up to five seconds to exit cooperatively and is terminated if it does not; terminal cancelled is recorded only after exit is confirmed.
- [ ] The active Data Generation Pin is released only after confirmed child exit and terminal durable cleanup.
- [ ] Already acknowledged task outcomes and already-published Results remain authoritative and available after cancellation.
- [ ] Every unfinished child Run becomes cancelled, while failed and succeeded sibling outcomes are retained without rollback or reinterpretation.
- [ ] Any DailyTrack independently seeded from a completed Strategy child remains intact.
- [ ] Cancellation removes live heartbeat, unchecked output, incomplete Checkpoints, inactive Attempt files, and now-unused private shared-artifact references through the durable cleanup path.
- [ ] Cancellation during retry wait, supervisor loss, API restart, object-store outage, and stale-child publication still converges to one fenced terminal outcome without leaking resumable work.
- [ ] A cancellation racing final acknowledgement has one deterministic winner: completed natural terminal state wins if it committed first; otherwise cancellation prevents the late acknowledgement.
- [ ] Late cancellation of an already naturally terminal Batch cannot rewrite succeeded, completed_with_failures, or failed into cancelled.
- [ ] A cancelled Batch is terminal and can never resume; rerunning unfinished inputs requires a new admission.
- [ ] Cancellation never deletes the Batch, completed child Runs, Results, or Batch history.
- [ ] Real process acceptance covers queued cancellation, cooperative exit, forced exit within the five-second budget, retry wait, lost supervisor, stale child, race resolution, exact replay, conflict, cleanup, and restart without arbitrary sleeps.

## Comments

- Parent: Research Batch Worker.
- Cancellation stops remaining calculation; it deliberately preserves work already completed and published.
