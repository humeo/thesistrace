# 09 — Recover Worker claims and surface availability

**What to build:** Make every Data Refresh kind recover safely from Worker loss
and show the Operator whether accepted work is actively serviceable, without
confusing durable submission with processing or publication.

**Blocked by:** 07 — Expose unified Dataset Operational Status.

**Status:** ready-for-agent

- [ ] Every claim uses a 15-minute lease renewed by a 30-second heartbeat, and
  only the current fenced owner may publish or complete the operation.
- [ ] An expired infrastructure claim is reclaimed on the same operation for at
  most three attempts; exhaustion becomes terminal `RETRY_EXHAUSTED`.
- [ ] Recovery reconciles whether publication completed before a crash before
  performing further collection or publication, preventing a duplicate visible
  Dataset Head effect.
- [ ] Market, Financial, and Industry operations all obey the same claim,
  heartbeat, fencing, recovery, and attempt policy.
- [ ] Business rejection and Financial degraded success are terminal domain
  outcomes and are never retried as infrastructure loss.
- [ ] A successfully persisted submission remains accepted while the Worker is
  unavailable, and the Console shows an explicit Worker-unavailable warning;
  persistence failure remains a rejected submission.
- [ ] The status view safely exposes running phase, attempt, last heartbeat, and
  availability without exposing a secret or raw diagnostic payload.
- [ ] A missing or placeholder Tushare Secret prevents Worker startup, and the
  secret is not delivered to Auth, Core API, Web, PostgreSQL, or browser state.
- [ ] Controlled-clock, real-PostgreSQL integration tests cover lost heartbeat,
  fencing, reclaim, publication-before-crash reconciliation, three-attempt
  exhaustion, unavailable submission, and recovery after restart without sleep.
- [ ] A real browser test proves accepted-with-warning, recovery to processing,
  attempt visibility, and terminal exhaustion copy.
