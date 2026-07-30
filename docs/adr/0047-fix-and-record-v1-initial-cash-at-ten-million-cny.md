---
status: accepted
---

# Fix and record V1 Initial Cash at ten million CNY

Every V1 Strategy Backtest starts with CNY 10,000,000 in cash before its first
execution open. The frozen Research Definition records
`initial_cash_cny: 10000000` explicitly even though V1 fixes the value, so a
ResearchRun never depends on an invisible runtime default.

ADR-0079 records this amount as both Gross NAV and Net NAV at the first
Research Window open, with no Actual Holdings. The first deployment occurs at
the following Research Session's open.

The Backtest permits no capital contribution, withdrawal, borrowing, leverage,
or negative cash. Initial Cash affects board-lot rounding, minimum fees, and
residual cash even though performance is primarily reported as returns.
