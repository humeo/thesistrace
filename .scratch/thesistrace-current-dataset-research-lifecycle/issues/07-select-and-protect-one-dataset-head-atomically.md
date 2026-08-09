# 07 — Select and protect one Dataset Head atomically

**What to build:** Select one authoritative mounted Dataset Head and coordinate
every Head move, Generation pin, and retention decision through one fenced
lifecycle boundary so readers never observe missing or mixed data.

**Blocked by:** 06 — Materialize and reopen a mounted Data Generation.

**Status:** ready-for-agent

- [ ] The Mounted Canonical Data Store exposes one authoritative Head manifest that resolves to one completely validated Data Generation.
- [ ] Head change uses compare-and-swap against an expected Generation; concurrent conflicting movers cannot both succeed.
- [ ] Readers observe either the complete old Head or the complete new Head and never a partially finalized candidate or mixed set of objects.
- [ ] An empty valid store has no Head and reports data readiness false, while an existing malformed or incompatible Head fails health and is never served as ready.
- [ ] When pin acquisition races a Head move, every successful pin resolves to one complete old or new Generation that remains readable for its lifetime; a compare-and-swap loser leaves Head unchanged, and restart resolves the same authoritative Head and live pins.
- [ ] Active pins record an owning Run or Tracking Advance Attempt, selected Generation, lifecycle state, and liveness; nonterminal pins are retention roots.
- [ ] A live candidate is protected only for its owning operation lifetime, and a finalized current Head remains protected independently of operation state.
- [ ] The Head and pin primitives are integration-tested with real PostgreSQL and a temporary mount while legacy Release consumers remain available for later migration.
