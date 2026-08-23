---
status: accepted
---

# Confirm DailyTrack Stop after the execution child exits

Stopping an `active` DailyTrack with a running Advance first moves the Track,
Advance, and Attempt to non-terminal `stopping`, advances the execution fence,
and signals the Tracking Worker supervisor. The supervisor gives its one child
a bounded cooperative grace interval, escalates to termination when needed,
and uses a five-second total confirmation budget while that owning supervisor
remains alive.

The Track becomes terminal `stopped`, the Attempt and Advance become
`cancelled`, and the Attempt-scoped Data Generation Pin is released only after
the child is confirmed exited. A stopped or fenced child has no publication
authority. If the supervisor is lost, the durable Stop intent remains and a
replacement may finalize it only after the old execution lease and child
ownership can no longer be live. That recovery path may exceed five seconds;
safety takes priority over reporting terminal Stop or releasing the Pin early.

Stopping an active Track with no running Attempt, or a blocked Track, completes
immediately because no execution child owns a Pin. In the same transaction it
cancels the unresolved Advance, current Attempt Cycle, retry eligibility, and
any pending claim so no Worker can start later work. Stop is irreversible and
never starts another Attempt. A `stopping` Track continues to count against the
Active DailyTrack Limit and cannot be retried, deleted, or advanced before it
reaches `stopped`.

After Stop reaches `stopped`, its disposable Working Cache is deleted. The
authoritative Tracking Head and Checkpoints remain until explicit DailyTrack
Deletion.

This applies ADR-0198's confirmed supervisor/child termination invariant to the
DailyTrack lifecycle without adding Tracking checkpoints or cross-Attempt
recovery state.
