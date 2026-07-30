# 14 — Handle suspension, delisting, and Strategy Benchmark

**What to build:** Preserve Strategy and Benchmark results when valid market
state governs a missing Open, while failing every unexplained market-data loss.

**Blocked by:** 03 — Publish Canonical EOD Price, adjustment, and Trading State; 04 — Publish Calendar, Universe, Industry, and Field Catalog; 13 — Apply A-share order rules and Transaction Costs.

**Status:** resolved

- [x] A held full-session-suspended position uses only its last real adjusted mark and emits Valuation Carry without creating market data or an executable price.
- [x] Partial suspension uses its observed daily Open and bar without carry.
- [x] Only a held position with a missing Open triggers local suspension then terminal-delisting lookup.
- [x] Effective terminal delisting removes all units at zero with no order, fill, Turnover, cost, or rejection.
- [x] Any unresolved missing Open fails calculation rather than becoming suspension or delisting.
- [x] Strategy Benchmark uses the selected Liquidity Universe, signal-session membership, and matching adjusted open-to-open interval.
- [x] Suspended Benchmark members retain equal weight with zero return and terminally delisted members with a valid start contribute -100%.

## Comments

- Missing held Opens now short-circuit through local suspension evidence,
  effective terminal delisting, then a hard data-quality failure.
- The selected Universe benchmark uses the same signal/entry/exit coordinate,
  preserves suspension weight, catches up on reopening, and recognizes a
  governed terminal loss once.
