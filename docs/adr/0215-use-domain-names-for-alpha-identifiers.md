---
status: accepted
---

# Use domain names for Alpha Identifiers

Alpha Formula authoring exposes concise domain concepts while the compiled
Alpha Expression and Data Generation retain exact namespaced Field References:

| Alpha Identifier | Canonical Field Reference |
|---|---|
| `open` | `price.open.adjusted` |
| `high` | `price.high.adjusted` |
| `low` | `price.low.adjusted` |
| `close` | `price.close.adjusted` |
| `volume` | `market.volume.shares` |
| `amount` | `market.turnover.cny` |
| `revenue` | `financial.income.total_revenue.latest_fy` |
| `net_profit` | `financial.income.net_profit_parent.latest_fy` |
| `operating_cash_flow` | `financial.cashflow.operating_cash_flow.latest_fy` |
| `assets` | `financial.balance_sheet.total_assets.latest_reported` |
| `liabilities` | `financial.balance_sheet.total_liabilities.latest_reported` |
| `equity` | `financial.balance_sheet.equity_parent.latest_reported` |

Adjustment, unit, reporting scope, and projection are fixed Field semantics,
not authoring choices, so repeating them in every Formula adds noise without
disambiguation. Namespaced Field References preserve those exact meanings and
remain distinct from user-facing Alpha Identifiers under ADR-0191.

This is a Product State hard cut. The former suffixed market and financial
names produce `UNKNOWN_IDENTIFIER`; there are no aliases, parser rewrites,
Browser Draft migrations, or compatibility paths.
