---
status: accepted
---

# Sell before buying target deficits in Alpha order

At a scheduled execution open, V1 values the portfolio immediately before
trading and divides pre-trade Net NAV by the actual number of selected Top-N
targets to obtain each instrument's ideal equal-weight target value. ADR-0081
defines Net state as the only decision-bearing accounting state.

The runtime first executes every eligible sell needed to reduce or remove
positions. It then sizes and executes buy deficits for selected targets in
descending Final Alpha order with `instrument_id` ascending as the exact-tie
break, using only the cash actually available after sells and costs. No buy can
exceed its ideal target value, borrow funds, or make cash negative. Cash
exhaustion may leave later selected targets underweight or unbought. ADR-0078
defines the shared candidate and buy-priority order. Affordability is
recalculated from Net Cash after each preceding fill and its costs.

Current instrument value is the position's Adjusted Holding Units multiplied
by its current Adjusted Research Price. ADR-0070 defines how a desired
position-value reduction maps proportionally to integer Execution Shares and
how its synthetic Research Settlement becomes available cash. A buy deficit
still maps to Execution Shares through Raw Market Price.

A blocked selected buy is skipped without adding an instrument outside the
Top-N set. Other selected targets may still buy up to their ideal values, and
unused capital remains cash. Execution constraints, costs, and rounding can
make actual weights differ from ideal target weights; Strategy Backtest retains
both target and actual weights. ADR-0049 defines board-specific share rounding.
