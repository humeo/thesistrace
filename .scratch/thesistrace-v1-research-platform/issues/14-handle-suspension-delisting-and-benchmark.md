# 14 — Handle suspension, delisting, and Strategy Benchmark

**What to build:** Preserve Strategy and Benchmark results when valid market
state governs a missing Open, while failing every unexplained market-data loss.

**Blocked by:** 03 — Publish Canonical EOD Price, adjustment, and Trading State; 04 — Publish Calendar, Universe, Industry, and Field Catalog; 13 — Apply A-share order rules and Transaction Costs.

**Status:** ready-for-agent

- [ ] A held full-session-suspended position uses only its last real adjusted mark and emits Valuation Carry without creating market data or an executable price.
- [ ] Partial suspension uses its observed daily Open and bar without carry.
- [ ] Only a held position with a missing Open triggers local suspension then terminal-delisting lookup.
- [ ] Effective terminal delisting removes all units at zero with no order, fill, Turnover, cost, or rejection.
- [ ] Any unresolved missing Open fails calculation rather than becoming suspension or delisting.
- [ ] Strategy Benchmark uses the selected Liquidity Universe, signal-session membership, and matching adjusted open-to-open interval.
- [ ] Suspended Benchmark members retain equal weight with zero return and terminally delisted members with a valid start contribute -100%.
