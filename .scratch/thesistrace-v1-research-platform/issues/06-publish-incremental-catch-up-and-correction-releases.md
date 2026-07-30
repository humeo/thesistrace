# 06 — Publish incremental, catch-up, and correction Releases

**What to build:** Advance the latest Dataset Release after close by writing
only new or corrected immutable objects while preserving one cumulative logical
snapshot and an auditable linear Release chain.

**Blocked by:** 03 — Publish Canonical EOD Price, adjustment, and Trading State; 04 — Publish Calendar, Universe, Industry, and Field Catalog.

**Status:** ready-for-agent

- [ ] Normal publication fetches only the new required source slices and never performs a complete-history correction scan.
- [ ] Each Release records its direct predecessor, appended session range, accepted correction change-set, schemas, objects, and checksums.
- [ ] A failed publication leaves latest and every older Release unchanged.
- [ ] Recovery after missed sessions publishes one real catch-up Release containing all intervening sessions without fabricating intermediate Releases.
- [ ] An accepted historical correction waits for a new-session publication and creates new objects while old Releases remain reproducible.
- [ ] Unchanged immutable objects are referenced rather than copied.
- [ ] Active DailyTrack work may be enqueued only after the Release commit and never controls publication success.
