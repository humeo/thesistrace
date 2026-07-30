# 10 — Build Forward Labels and Effective Factor Samples

**What to build:** Pair the shared Final Alpha Cross-Section with independently
resolved 1-, 5-, and 20-session next-open labels and explicit availability
reasons.

**Blocked by:** 03 — Publish Canonical EOD Price, adjustment, and Trading State; 04 — Publish Calendar, Universe, Industry, and Field Catalog; 09 — Evaluate Alpha Expressions and Alpha Matrices.

**Status:** ready-for-agent

- [ ] Labels use adjusted Opens at `t+1` and `t+1+h` and remain attributed to signal session `t`.
- [ ] Each horizon joins labels without recalculating or changing the Final Alpha Cross-Section.
- [ ] Release-end censoring, confirmed unavailable Opens, and unexplained data failure remain distinct.
- [ ] A missing or terminally unavailable entry produces no Label.
- [ ] Valid entry followed by effective terminal delisting on or before exit produces exactly -100%.
- [ ] Full-session-suspended exit remains unavailable while partial-session states use their valid daily Open.
- [ ] The standard 504-session window respects the theoretical 502, 498, and 483 maximum labeled counts.
