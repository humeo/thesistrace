# 06 — Publish incremental, catch-up, and correction Releases

**What to build:** Advance the latest Dataset Release after close by writing
only new or corrected immutable objects while preserving one cumulative logical
snapshot and an auditable linear Release chain.

**Blocked by:** 03 — Publish Canonical EOD Price, adjustment, and Trading State; 04 — Publish Calendar, Universe, Industry, and Field Catalog.

**Status:** resolved

- [x] Normal publication fetches only the new required source slices and never performs a complete-history correction scan.
- [x] Each Release records its direct predecessor, appended session range, accepted correction change-set, schemas, objects, and checksums.
- [x] A failed publication leaves latest and every older Release unchanged.
- [x] Recovery after missed sessions publishes one real catch-up Release containing all intervening sessions without fabricating intermediate Releases.
- [x] An accepted historical correction waits for a new-session publication and creates new objects while old Releases remain reproducible.
- [x] Unchanged immutable objects are referenced rather than copied.
- [x] Active DailyTrack work may be enqueued only after the Release commit and never controls publication success.

## Comments

- Added fixture-backed new-session, catch-up, and correction publication with a
  direct predecessor chain and content-addressed source/canonical deltas.
- Added credential-gated live post-close publication that fetches only the
  current frontier-to-`as_of` Tushare slices, supports one catch-up Release,
  retains source responses, and reuses predecessor objects while recomputing
  dynamic front-adjusted prices from retained factors.
- Verified correction-only rejection, latest-pointer failure atomicity,
  idempotency, old Release reproducibility, object reuse, and cumulative
  materialization through public APIs.
