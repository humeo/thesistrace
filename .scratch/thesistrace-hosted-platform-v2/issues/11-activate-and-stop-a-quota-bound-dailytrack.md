# 11 — Activate and stop a quota-bound DailyTrack

**What to build:** Let a User idempotently activate Daily Tracking from one
successful ResearchRun, inspect its owned root state, and stop it permanently
while enforcing the Personal Workspace Active DailyTrack limit.

**Blocked by:** 07 — Run one Research Workflow through Temporal; 09 — Enforce the Personal Workspace Quota Profile; `thesistrace-bounded-research-storage/04 — Seed a bounded Working Cache when activating DailyTrack`.

**Status:** complete

- [x] Only a succeeded ResearchRun with a complete Result Bundle can seed a Personal Workspace-owned DailyTrack.
- [x] Activation pins the frozen Definition, Dataset Release, Tracking Origin, numeric contract, and Terminal Strategy State and publishes one Activation Checkpoint plus the bounded latest-only Working Cache.
- [x] Repeating an activation idempotency key returns the same DailyTrack and does not consume another active-Track quota unit.
- [x] Activation is rejected with the active-Track quota dimension when the effective Personal Workspace limit is reached, including a lower Operator override.
- [x] A valid identifier from another Personal Workspace cannot activate, inspect, or stop the Track and receives no existence disclosure.
- [x] Stopping a Track is terminal, fences queued or running later publication, releases the active-Track quota immediately, and durably schedules idempotent Working Cache cleanup.
- [x] A seed ResearchRun cannot be deleted while a retained DailyTrack still references it.

**Acceptance evidence:** Activation now admits one short-lived, Workspace-scoped
reservation under the shared quota lock, performs bounded Working Cache
calculation without holding a database transaction or publication lock, then
atomically promotes the Activation Checkpoint and creates the retained
DailyTrack. Active Tracks plus reservations consume the effective quota.
Concurrent uses of one idempotency key wait on the owning staging lock and
return the same Track, while different keys cannot over-admit or duplicate the
expensive calculation.

Staging journals and reservation reconciliation cover crashes before metadata
commit, commit acknowledgement loss, live activation, and orphan cleanup
without age-based guesses. Hosted startup and Compute recovery use restricted
cross-Workspace functions to preserve active or reservation-owned caches and
complete durable stop cleanup without exposing those records through User
routes. Stop row-locks the Track, advances its fence, cancels later attempts,
blocks pending or running publication, releases quota immediately, and limits
the synchronous cleanup path to that Track; only background reconciliation
performs a global orphan sweep.

Real isolated PostgreSQL acceptance passed `2` tests covering RLS isolation,
three-phase concurrent quota admission, no-identity cache preservation and
stop recovery, effective override locking, seed-Run retention, and replacement
admission. Focused local suites passed `44` tests with `5` environment-gated
skips, plus the final stop-scope regression passed `10` tests with one
environment-gated skip. The final complete Python suite passed `140` tests
with `9` environment-gated skips. Independent Standards and Spec reviews both
passed after the reservation, idempotency, crash-window, cross-Workspace
recovery, and stop-path performance corrections.
