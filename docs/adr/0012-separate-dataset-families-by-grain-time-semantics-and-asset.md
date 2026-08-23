---
status: accepted
---

# Separate Dataset Families by grain, time semantics, and asset

ThesisTrace groups Canonical Market Data into versioned Dataset Families.
Fields belong to one family only when they share the same asset boundary,
primary-key grain, and information-availability semantics. A new field with
those same properties may extend the family; different properties require a
separate family.

End-of-day equity bars belong to `equity.eod_price`. Source Adjustment Factors
belong to the dated `equity.adjustment_factor` family because their source
availability differs from post-close bars; adjusted OHLC remains a
deterministic derivative in `equity.eod_price`. Point-in-Time Financial Data
uses separate statement and projection families because its report-period and
availability semantics differ from market sessions. Trading state, industry
classification, and liquidity-universe membership remain their own dated
families rather than columns copied into the price table. ADR-0074 defines
`equity.trading_state`.

Futures, options, and convertible bonds require separate asset
families because their identifiers, calendars, contract terms, and lifecycle
events differ from equities. Shared orchestration may consume multiple
families, but the system does not retrofit those instruments into the equity
contract or create one universal wide table.
