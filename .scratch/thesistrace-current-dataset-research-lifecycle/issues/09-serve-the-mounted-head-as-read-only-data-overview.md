# 09 — Serve the mounted Head as read-only Data Overview

**What to build:** Let ordinary users inspect the readiness, coverage, and
freshness of the mounted current Dataset without exposing mutation, operator
work, Generation history, or the retired Dataset Release resource model.

**Blocked by:** 07 — Select and protect one Dataset Head atomically.

**Status:** complete

- [x] An empty valid Mounted Canonical Data Store starts in degraded read-only mode and returns `readiness = false` without fabricating Coverage, data-through, or refresh values.
- [x] A valid prepared Head returns only Dataset Coverage start and end, data-through Research Session, nullable `last_refresh_at`, and readiness, with values matching the authoritative Head and successful Refresh state.
- [x] Data Overview exposes no Generation identifier, Head manifest, internal preparation time, Refresh receipt or Attempt, operator failure, object location, or historical chain.
- [x] A malformed or incompatible existing Head prevents healthy data service startup and is never presented as ready, distinct from the supported empty-store state.
- [x] Ordinary product API Data mutation, Dataset Release list, and Dataset Release detail routes are absent rather than returning an authorization denial.
- [x] The Data page shows only Coverage, data-through, nullable last successful refresh time, readiness, and a manual read refresh; Update controls, 250-ms mutation polling, update outcomes, Release or Generation identifiers, predecessor chains, history, and operator status are absent.
- [x] API and Worker restart reopen the same prepared Head and return the same Overview without contacting Tushare or any other DataSource.
- [x] Real Core HTTP tests with PostgreSQL, RustFS, and a temporary mount prove the public contract; a focused rendered-page test proves the Data page, while the cross-resource browser journey remains separate.

## Comments

- Implemented by `12f8051 feat(data): serve mounted head overview`; public fixture runtime settings were removed in `5256e35`, and review hardening/restored active-product acceptance is in `b053b61` (with `14044be` explicitly reverting the over-broad test deletion from `b5b4fb2`).
- Public Data now has exactly one read-only Overview route and page. Empty stores degrade to not-ready; prepared Heads are fully resolved and validated; malformed or projection-tampered Heads fail; `last_refresh_at` remains nullable and is read from PostgreSQL refresh state.
- Production startup and ordinary Worker/API reads use only the configured mount and never construct a Fixture or Tushare DataSource. Obsolete public Update/Release acceptance was removed, while 65 active Definition/ResearchRun/DailyTrack acceptance tests remain collected and use a test-only canonical fixture factory.
- Focused verification passed: Ruff; Web typecheck; 4 rendered Data/Shell tests; 71 architecture/source-contract tests; and 4 real PostgreSQL/RustFS + temporary-mount HTTP/process-restart tests (`95 deselected`) in 75.23 seconds. The isolated projects removed containers, volumes, networks, and host-mounted canonical data.
- Spec review against fixed point `80bdfbd` ended with no findings. Standards review ended with no material findings; its remaining P3 test-helper deduplication suggestion is intentionally deferred to the owning Run/Track migration tickets rather than widening this cutover.
