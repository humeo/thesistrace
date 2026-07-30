---
status: accepted
---

# Require a one-to-twenty-session Rebalance Interval

Every V1 Research Definition must contain an explicit integer
`rebalance_every_sessions` between 1 and 20 inclusive. The runtime does not
restrict the value to a smaller enumeration such as 1, 5, and 20, and a frozen
definition never depends on a runtime default.

One ResearchRun uses only its one frozen interval. Supporting every integer in
the range does not cause the runtime to execute or compare additional rebalance
schedules.
