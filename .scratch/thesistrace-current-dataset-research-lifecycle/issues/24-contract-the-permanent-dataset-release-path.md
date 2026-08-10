# 24 — Contract the permanent Dataset Release path

**What to build:** Complete the current-data cutover by guarding unsupported
legacy state, removing the permanent Dataset Release graph and default Fixture
wiring, and leaving mounted Head/Generation as the only active market-data
lifecycle.

**Blocked by:** 09 — Serve the mounted Head as read-only Data Overview; 11 — Recover and fence failed or concurrent Refresh work; 15 — Retry and Rerun against the then-current Head; 20 — Collect retired Data Generations safely; 21 — Guard development cutover with explicit Reset; 23 — Contract DailyTrack Release-coordinate compatibility.

**Status:** complete

- [x] Ordinary startup and schema migration detect nonempty unsupported Release-bound state, preserve its PostgreSQL rows, RustFS objects, and mounted data, and fail with a stable diagnostic directing the operator to Development Reset or a separately managed migration.
- [x] Development Reset remains independently callable after that guard triggers; following a successful Reset, migration can resume and complete contraction.
- [x] In a reset-clean state, active schema and runtime remove Release graph, latest and predecessor state, Run and receipt Release binding, Release loader and successor callbacks, and isolated legacy DailyTrack physical structures.
- [x] No legacy Release-to-Generation mapping is created and no legacy Result or Track is migrated; only post-cutover Results and Tracks are required to survive restart and input Generation collection.
- [x] Default API and Worker runtime read the mounted Head and never construct Fixture or Tushare DataSources; Fixture remains available only as an explicitly injected deterministic test adapter.
- [x] Empty valid store starts with `readiness = false`, a malformed Head fails health, and a prepared valid Head becomes ready without automatic Bootstrap or Refresh.
- [x] Fresh Bootstrap or a prepared mount can restore a usable Head after Reset, while ordinary startup itself remains read-only and network-independent.
- [x] Final architecture guards inspect active runtime, schema, API, and Web contracts without flagging historical migration ledgers, ADRs, archived documents, or intentionally retained test adapters.
