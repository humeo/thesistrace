---
status: accepted
---

# Require a one-to-twenty-session Rebalance Interval

Every Strategy Backtest ResearchRun freezes an explicit integer
`rebalance_every_sessions` from 1 through 20; an invalid Browser Draft is
rejected instead of receiving a runtime default. Every integer in that range is
valid rather than only a smaller enumeration such as 1, 5, and 20.

One ResearchRun uses only its one immutable interval. Supporting every integer
in the range does not cause the runtime to execute or compare additional
rebalance schedules.
