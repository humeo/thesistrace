# 03 — Trace the DailyTrack lifecycle end to end

**What to build:** Let an operator follow one DailyTrack through its Advance,
Attempts, progress, retries, blocking, Tracking Checkpoint publication, Stop,
and terminal failures using the same structured event contract as ResearchRun.

**Blocked by:** 02 — Trace the ResearchRun lifecycle end to end

**Status:** ready-for-agent

- [ ] DailyTrack events use the canonical JSON contract and carry `track_id`, `attempt_id`, and Worker role whenever those identities exist.
- [ ] The observable lifecycle covers claim, Tracking Advance and Attempt start, meaningful state transition, phase completion, retry scheduling, blocked state, Tracking Checkpoint publication, Stop confirmation, and terminal failure.
- [ ] Events distinguish authoritative Tracking Head movement from in-flight Tracking Progress and never describe uncommitted work as published.
- [ ] Publication and success events are emitted only after the complete frozen Target has atomically advanced the authoritative Head.
- [ ] Normal progress is INFO, retry scheduling and operator-actionable blocking are WARNING, and unexpected or terminal internal failure is ERROR.
- [ ] Idle Tracking queue polls, no-work polls, retry waiting without a transition, and successful lease heartbeat renewals do not emit INFO events.
- [ ] Safe failure and retry facts remain visible while command payloads, Strategy state, Checkpoint content, object keys, physical paths, SQL, raw dependency errors, and exception messages remain absent.
- [ ] Ad hoc Tracking lifecycle printing or a second event schema is removed from the affected path in the same change; no compatibility emitter or dual-write period remains.
- [ ] Real PostgreSQL, RustFS, Tracking Worker, and child-process tests prove correlated event timelines agree with committed state for successful Advance, retry, blocked state, Checkpoint publication, Stop, and terminal failure.
- [ ] Tests prove successful heartbeat renewal creates no INFO noise and that an unchanged retry or blocked state is not logged repeatedly.
- [ ] Telemetry loss has no effect on claim, lease, fencing, retry Cycle, blocking, Stop, recovery, or Tracking Checkpoint publication.
- [ ] DailyTrack scheduling, Head-only recovery, retry, Stop, Checkpoint, and equivalence contracts remain unchanged.

## Comments

- Parent: Basic Operational Observability.
