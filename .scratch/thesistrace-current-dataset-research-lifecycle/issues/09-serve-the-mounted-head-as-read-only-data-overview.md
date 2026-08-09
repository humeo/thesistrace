# 09 — Serve the mounted Head as read-only Data Overview

**What to build:** Let ordinary users inspect the readiness, coverage, and
freshness of the mounted current Dataset without exposing mutation, operator
work, Generation history, or the retired Dataset Release resource model.

**Blocked by:** 07 — Select and protect one Dataset Head atomically.

**Status:** ready-for-agent

- [ ] An empty valid Mounted Canonical Data Store starts in degraded read-only mode and returns `readiness = false` without fabricating Coverage, data-through, or refresh values.
- [ ] A valid prepared Head returns only Dataset Coverage start and end, data-through Research Session, nullable `last_refresh_at`, and readiness, with values matching the authoritative Head and successful Refresh state.
- [ ] Data Overview exposes no Generation identifier, Head manifest, internal preparation time, Refresh receipt or Attempt, operator failure, object location, or historical chain.
- [ ] A malformed or incompatible existing Head prevents healthy data service startup and is never presented as ready, distinct from the supported empty-store state.
- [ ] Ordinary product API Data mutation, Dataset Release list, and Dataset Release detail routes are absent rather than returning an authorization denial.
- [ ] The Data page shows only Coverage, data-through, nullable last successful refresh time, readiness, and a manual read refresh; Update controls, 250-ms mutation polling, update outcomes, Release or Generation identifiers, predecessor chains, history, and operator status are absent.
- [ ] API and Worker restart reopen the same prepared Head and return the same Overview without contacting Tushare or any other DataSource.
- [ ] Real Core HTTP tests with PostgreSQL, RustFS, and a temporary mount prove the public contract; a focused rendered-page test proves the Data page, while the cross-resource browser journey remains separate.
