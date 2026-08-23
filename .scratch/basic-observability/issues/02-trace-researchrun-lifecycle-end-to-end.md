# 02 — Trace the ResearchRun lifecycle end to end

**What to build:** Let an operator follow one ResearchRun from claim through its
Attempts, committed phases, Checkpoints, retries, publication, cancellation, and
terminal outcome using the canonical structured events, without corrupting the
supervisor-child protocol or changing Research semantics.

**Blocked by:** 01 — Emit safe structured HTTP events

**Status:** ready-for-agent

- [ ] ResearchRun events use the canonical JSON contract and carry `run_id`, `attempt_id`, and Worker role whenever those identities exist.
- [ ] The observable lifecycle covers claim, Attempt start, meaningful state transition, phase completion, private Checkpoint commit, retry scheduling, Result publication, cancellation confirmation, success, and terminal failure.
- [ ] A success or publication event is emitted only after the represented database transaction, acknowledgement, or object publication has committed.
- [ ] Normal lifecycle progress is INFO, retryable failure and retry scheduling are WARNING, and unexpected or terminal internal failure is ERROR.
- [ ] Idle Research queue polls, no-work polls, and successful lease heartbeat renewals do not emit INFO events.
- [ ] Safe `failure_code` is preserved while Formula, Hypothesis, command payload, Result or Checkpoint payload, DSN, SQL, object key, path, raw dependency error, and raw exception message remain absent.
- [ ] Supervised child stdout remains exclusively the parent-child protocol and is never passed through the operational formatter.
- [ ] Child operational evidence uses stderr with inherited correlation or an allowlisted supervisor event; raw child protocol or calculation payloads are never forwarded to container logs.
- [ ] The existing injectable Worker event seam remains usable by tests while production emission uses the canonical event boundary.
- [ ] Ad hoc Research lifecycle printing or a second event schema is removed from the affected path in the same change; no compatibility emitter or dual-write period remains.
- [ ] Real PostgreSQL, RustFS, Worker, and child-process tests prove correlated event timelines agree with committed state for success, retry, publication, cancellation, and terminal failure.
- [ ] Tests prove that a rolled-back transition emits no success event and that telemetry loss has no effect on claim, lease, fencing, retry, cancellation, recovery, or publication.
- [ ] ResearchRun calculation, scheduling, retry, cancellation, Checkpoint, Result, and numeric contracts remain unchanged.

## Comments

- Parent: Basic Operational Observability.
