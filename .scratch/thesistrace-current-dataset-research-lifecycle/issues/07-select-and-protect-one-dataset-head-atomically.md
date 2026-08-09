# 07 — Select and protect one Dataset Head atomically

**What to build:** Select one authoritative mounted Dataset Head and coordinate
every Head move, Generation pin, and retention decision through one fenced
lifecycle boundary so readers never observe missing or mixed data.

**Blocked by:** 06 — Materialize and reopen a mounted Data Generation.

**Status:** complete

- [x] The Mounted Canonical Data Store exposes one authoritative Head manifest that resolves to one completely validated Data Generation.
- [x] Head change uses compare-and-swap against an expected Generation; concurrent conflicting movers cannot both succeed.
- [x] Readers observe either the complete old Head or the complete new Head and never a partially finalized candidate or mixed set of objects.
- [x] An empty valid store has no Head and reports data readiness false, while an existing malformed or incompatible Head fails health and is never served as ready.
- [x] When pin acquisition races a Head move, every successful pin resolves to one complete old or new Generation that remains readable for its lifetime; a compare-and-swap loser leaves Head unchanged, and restart resolves the same authoritative Head and live pins.
- [x] Active pins record an owning Run or Tracking Advance Attempt, selected Generation, lifecycle state, and liveness; nonterminal pins are retention roots.
- [x] A live candidate is protected only for its owning operation lifetime, and a finalized current Head remains protected independently of operation state.
- [x] The Head and pin primitives are integration-tested with real PostgreSQL and a temporary mount while legacy Release consumers remain available for later migration.

## Comments

- Implemented by `4fb6e4a feat(data): fence the mounted dataset head`; review hardening is in `b7afa96`, `fcbdd16`, `4015c48`, `2c8b5ce`, and `2bd10bb`.
- `HEAD.json` is one bounded, canonical, atomically replaced pointer to a fully reopened immutable Generation. Filesystem locking and expected-Generation CAS prevent two movers from winning; symlink, FIFO, oversized, growing, malformed, missing, mixed, and cross-mount candidates are rejected.
- PostgreSQL uses one short advisory lifecycle fence for Candidate ownership, Head movement, Run/Track pins, heartbeat, release, and restart recovery. Candidate resolution is a context-managed, single-use capability, so failed database validation cannot retain or transplant Canonical data.
- Tests use different Canonical contents and data identities for every competing Generation, hold the real file/advisory locks before releasing contenders, inject rename and post-Head database-completion failures, and verify complete old/new data, durable pins, Candidate state, and restart behavior.
- Focused Head/Generation tests passed `29 passed in 6.16s`; the complete Data/Adapter suite and Ruff checks passed. A fresh PostgreSQL/RustFS environment passed Lifecycle, migration idempotency, restart, and unchanged legacy Release-consumer acceptance (`5 passed in 7.13s`); all dedicated containers, network, and volumes were removed afterward.
- The final schema is defined once in `0006`; no compatibility migration was added for obsolete development database state. Safe physical collection remains owned by Ticket 20 rather than exposing an unsafe retention snapshot in this foundation ticket.
- Standards and Spec reviews used fixed point `2bd10bb` and both ended with zero findings.
