# 03 — Trace the DailyTrack lifecycle end to end

**What to build:** Let an operator follow one DailyTrack through its Advance,
Attempts, progress, retries, blocking, Tracking Checkpoint publication, Stop,
and terminal failures using the same structured event contract as ResearchRun.

**Blocked by:** 02 — Trace the ResearchRun lifecycle end to end

**Status:** complete

- [x] DailyTrack events use the canonical JSON contract and carry `track_id`, `attempt_id`, and Worker role whenever those identities exist.
- [x] The observable lifecycle covers claim, Tracking Advance and Attempt start, meaningful state transition, phase completion, retry scheduling, blocked state, Tracking Checkpoint publication, Stop confirmation, and terminal failure.
- [x] Events distinguish authoritative Tracking Head movement from in-flight Tracking Progress and never describe uncommitted work as published.
- [x] Publication and success events are emitted only after the complete frozen Target has atomically advanced the authoritative Head.
- [x] Normal progress is INFO, retry scheduling and operator-actionable blocking are WARNING, and unexpected or terminal internal failure is ERROR.
- [x] Idle Tracking queue polls, no-work polls, retry waiting without a transition, and successful lease heartbeat renewals do not emit INFO events.
- [x] Safe failure and retry facts remain visible while command payloads, Strategy state, Checkpoint content, object keys, physical paths, SQL, raw dependency errors, and exception messages remain absent.
- [x] Ad hoc Tracking lifecycle printing or a second event schema is removed from the affected path in the same change; no compatibility emitter or dual-write period remains.
- [x] Real PostgreSQL, RustFS, Tracking Worker, and child-process tests prove correlated event timelines agree with committed state for successful Advance, retry, blocked state, Checkpoint publication, Stop, and terminal failure.
- [x] Tests prove successful heartbeat renewal creates no INFO noise and that an unchanged retry or blocked state is not logged repeatedly.
- [x] Telemetry loss has no effect on claim, lease, fencing, retry Cycle, blocking, Stop, recovery, or Tracking Checkpoint publication.
- [x] DailyTrack scheduling, Head-only recovery, retry, Stop, Checkpoint, and equivalence contracts remain unchanged.

## Comments

- Parent: Basic Operational Observability.
- Added canonical post-commit Tracking events for claim, Attempt and Advance
  start, committed phases, retry/block transitions, Worker-loss recovery,
  Checkpoint publication, authoritative Head movement, Stop confirmation,
  heartbeat failure, fencing, and terminal failure. Idle polls, retry waiting,
  and successful heartbeats remain silent.
- Shared the non-blocking operational sink with ResearchRun, while preserving
  the deterministic callback seam and mapping raw child identities to
  `track_id`. Telemetry callback failure cannot alter claims, retries, Stop, or
  publication.
- Initial review found an unsafe Working Cache traceback path; it was replaced
  with an allowlisted WARNING after the authoritative Head commit. A real
  unavailable-cache test proves the Head still advances and a canary path is
  absent from serialized Worker output. A smoke-contract Attempt-prefix error
  and a private cache monkeypatch in the first fix were also corrected. Final
  independent Standards and Spec re-reviews were clean.
- Verification: focused architecture lane 48 passed; current-contract real
  PostgreSQL/RustFS/Tracking Worker/child-process lanes 9 passed; Ruff passed;
  complete backend fast lane 539 passed with 5 existing warnings; Web typecheck
  passed; Web shell lane 56 passed. The older DailyTrack detail fixture still
  returns the separately reproduced pre-existing 422 before reaching its Worker
  assertion, matching the Ticket 02 base behavior.

## Plan

1. Add failing contracts around the existing Tracking Worker event seam for
   claim, Advance/Attempt start, committed progress and phase boundaries,
   retry/wait transitions, blocking, Checkpoint publication, Stop, terminal
   failure, idle polls, successful heartbeats, and telemetry loss.
2. Normalize Tracking Worker output through the canonical event boundary with
   `track_id`, `attempt_id`, and `worker_role=tracking`, while keeping child
   stdout protocol-only and retaining deterministic callback injection.
3. Return minimal committed lifecycle facts from claim, publish, retry,
   blocking, Stop, recovery, and failure transactions; emit only after those
   transactions complete with INFO/WARNING/ERROR chosen from the committed
   outcome, and suppress unchanged retry/blocked states.
4. Prove authoritative Tracking Head movement separately from in-flight
   Progress using real PostgreSQL, RustFS, Tracking Worker, and child-process
   acceptance tests, including safe failure fields and lossy telemetry.
5. Run focused architecture and real-dependency lanes, Ruff, the complete fast
   backend lane, and Web gates; complete independent Standards and Spec review,
   fix and re-review, update this tracker, and create one Ticket 03 commit.
