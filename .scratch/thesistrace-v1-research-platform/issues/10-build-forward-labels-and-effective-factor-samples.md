# 10 — Build Forward Labels and Effective Factor Samples

**What to build:** Pair the shared Final Alpha Cross-Section with independently
resolved 1-, 5-, and 20-session next-open labels and explicit availability
reasons.

**Blocked by:** 03 — Publish Canonical EOD Price, adjustment, and Trading State; 04 — Publish Calendar, Universe, Industry, and Field Catalog; 09 — Evaluate Alpha Expressions and Alpha Matrices.

**Status:** resolved

- [x] Labels use adjusted Opens at `t+1` and `t+1+h` and remain attributed to signal session `t`.
- [x] Each horizon joins labels without recalculating or changing the Final Alpha Cross-Section.
- [x] Release-end censoring, confirmed unavailable Opens, and unexplained data failure remain distinct.
- [x] A missing or terminally unavailable entry produces no Label.
- [x] Valid entry followed by effective terminal delisting on or before exit produces exactly -100%.
- [x] Full-session-suspended exit remains unavailable while partial-session states use their valid daily Open.
- [x] The standard 504-session window respects the theoretical 502, 498, and 483 maximum labeled counts.

## Comments

- Added independent 1/5/20 next-open-to-open Label resolution over the shared
  Alpha Matrix, with signal-session attribution and reason-coded unavailable
  observations.
- Kernel acceptance verifies timing, 502/498/483 maxima, right censoring,
  full-session suspension, and terminal -100% handling.
