# 02 — Trace the ResearchRun lifecycle end to end

**What to build:** Let an operator follow one ResearchRun from claim through its
Attempts, committed phases, Checkpoints, retries, publication, cancellation, and
terminal outcome using the canonical structured events, without corrupting the
supervisor-child protocol or changing Research semantics.

**Blocked by:** 01 — Emit safe structured HTTP events

**Status:** complete

- [x] ResearchRun events use the canonical JSON contract and carry `run_id`, `attempt_id`, and Worker role whenever those identities exist.
- [x] The observable lifecycle covers claim, Attempt start, meaningful state transition, phase completion, private Checkpoint commit, retry scheduling, Result publication, cancellation confirmation, success, and terminal failure.
- [x] A success or publication event is emitted only after the represented database transaction, acknowledgement, or object publication has committed.
- [x] Normal lifecycle progress is INFO, retryable failure and retry scheduling are WARNING, and unexpected or terminal internal failure is ERROR.
- [x] Idle Research queue polls, no-work polls, and successful lease heartbeat renewals do not emit INFO events.
- [x] Safe `failure_code` is preserved while Formula, Hypothesis, command payload, Result or Checkpoint payload, DSN, SQL, object key, path, raw dependency error, and raw exception message remain absent.
- [x] Supervised child stdout remains exclusively the parent-child protocol and is never passed through the operational formatter.
- [x] Child operational evidence uses stderr with inherited correlation or an allowlisted supervisor event; raw child protocol or calculation payloads are never forwarded to container logs.
- [x] The existing injectable Worker event seam remains usable by tests while production emission uses the canonical event boundary.
- [x] Ad hoc Research lifecycle printing or a second event schema is removed from the affected path in the same change; no compatibility emitter or dual-write period remains.
- [x] Real PostgreSQL, RustFS, Worker, and child-process tests prove correlated event timelines agree with committed state for success, retry, publication, cancellation, and terminal failure.
- [x] Tests prove that a rolled-back transition emits no success event and that telemetry loss has no effect on claim, lease, fencing, retry, cancellation, recovery, or publication.
- [x] ResearchRun calculation, scheduling, retry, cancellation, Checkpoint, Result, and numeric contracts remain unchanged.

## Comments

- Parent: Basic Operational Observability.
- Replaced the production Worker's ad hoc JSON printer with the canonical safe
  event adapter while preserving the injectable Worker event seam and the
  supervised child's stdout-only protocol boundary.
- Added post-commit lifecycle events for claim, Attempt start, state and phase
  boundaries, Checkpoint commit, retry, Worker-loss recovery, Result
  publication, cancellation, success, fencing, heartbeat failure, and terminal
  failure. Telemetry callbacks are non-blocking and cannot change product state.
- Initial Standards and Spec findings were fixed: multi-chunk phase completion
  is emitted only at the real phase boundary; fencing uses a boundary-neutral
  event; private adapter testing was removed; lease-expiry recovery reports
  retry and exhaustion; queued and no-active-Attempt cancellation reports only
  after commit; and the dedicated multi-chunk test was reduced to 140 sessions.
  Both independent final re-reviews were clean.
- Verification: focused architecture lane 19 passed; current-contract real
  PostgreSQL/RustFS/Worker/child-process lanes 9 passed; Ruff passed; complete
  backend fast lane 539 passed with 5 existing warnings; Web typecheck passed;
  Web shell lane 56 passed. The broad integration lane still has the separately
  reproduced pre-existing `FIELD_UNAVAILABLE_IN_CURRENT_DATA` 422 failures in
  stale fixtures; the same failure reproduces at the Ticket 02 base commit.

## Plan

1. Add failing contract tests around the existing injectable Worker event seam
   for claim/Attempt start, committed phase and Checkpoint events, retry versus
   terminal failure, publication/success, cancellation, telemetry loss, and
   omission of idle polls, heartbeats, child protocol payloads, and canaries.
2. Replace the production Worker's ad hoc JSON printer with a strict adapter to
   the canonical operational event boundary while keeping the injectable event
   callback used by deterministic and real-dependency tests.
3. Emit ResearchRun lifecycle facts only after their owning PostgreSQL or
   Publication transaction returns successfully; use INFO for normal progress,
   WARNING for retry scheduling, and ERROR for terminal failure.
4. Preserve supervised child stdout as protocol-only and expose only
   allowlisted parent-side child lifecycle evidence with inherited `run_id`,
   `attempt_id`, and `worker_role`; remove affected direct lifecycle logging.
5. Run focused architecture and real PostgreSQL/RustFS/Worker/child acceptance
   lanes, Ruff, the complete backend fast lane, Web gates, then perform
   independent Standards and Spec review, fix and re-review, update this
   tracker, and create one Ticket 02 commit.
