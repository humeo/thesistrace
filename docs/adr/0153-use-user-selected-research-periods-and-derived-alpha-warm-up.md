---
status: accepted
---

# Use user-selected Research Periods and derived Alpha warm-up

Every ResearchRun freezes inclusive natural `start_date` and `end_date` values,
maps them to the contained Research Sessions, and rejects a range with no
Research Session. Calculation Warm-up is derived from the Alpha Expression's
Effective Alpha Lookback, supplies inputs only, and never contributes signals,
orders, Factor observations, or reported Strategy results; insufficient history
fails explicitly instead of shifting the requested period or filling values.

Forward Return Labels never read after the Research Period end, and unavailable
right-censored metrics remain `null` with zero coverage rather than becoming a
failure or numeric zero. Strategy Backtest begins from its all-cash baseline at
the first Research Session, schedules work only when execution and later
valuation remain inside the period, and ends with a Terminal Valuation without
forced liquidation.

Factor Evaluation and Strategy Backtest publish only the Result fields valid
for their Research Kind. The exact Result byte budget is
`ceil(research_period_session_count / 504) * 1 MiB`; exceeding it fails atomic
publication rather than truncating required output. This permits short and long
research periods while keeping warm-up, right-censoring, and retained Result
size explicit.
