---
status: accepted
---

# Report daily actual Cash Ratio and three aggregates

Strategy Backtest derives each Research Session's actual Cash Ratio from the retained Net Cash and Net NAV in Strategy Daily Observations because execution constraints can leave the portfolio partially uninvested. It reports the arithmetic mean, maximum with date, and ending value without storing a duplicate Cash Ratio series or imposing a target cash allocation.
