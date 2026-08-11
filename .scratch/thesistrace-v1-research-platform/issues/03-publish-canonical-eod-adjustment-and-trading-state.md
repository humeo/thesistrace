# 03 — Publish Canonical EOD Price, adjustment, and Trading State

**What to build:** Turn accepted fixture source facts into the complete V1 EOD
Price, Adjustment Factor, dynamic front-adjusted price, price-limit, and Trading
State contracts inside the Bootstrap Release.

**Blocked by:** 02 — Publish a fixture Bootstrap Release.

**Status:** resolved

- [x] All eleven accepted daily fields are retained in source units and mapped to their Canonical fields and units.
- [x] Adjustment Factors, latest-factor reference scales, and adjusted OHLC are deterministic and Generation-owned.
- [x] Normal, partial-opening suspension, after-open suspension, and full-session suspension fixtures resolve to exactly one Trading State.
- [x] Full-session suspension creates no EOD Price row; unexplained or contradictory absence fails publication.
- [x] Session-specific upper and lower price limits are published for execution.
- [x] Canonical decimals are not persisted as binary floating-point source facts.

## Comments

- Published source-unit EOD facts, canonical decimal strings, dynamic
  front-adjusted OHLC, Trading State, and session price limits.
- Verified all four Trading States, suspension absence, adjustment arithmetic,
  and decimal persistence through the immutable object API.
