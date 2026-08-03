---
status: accepted
---

# Require a one-to-twenty-session Rebalance Interval

Every successful V1 Run must resolve an explicit integer
`rebalance_every_sessions` from the saved Research Definition between 1 and 20
inclusive. A Definition may be saved before this value is valid. The runtime
does not restrict the value to a smaller enumeration such as 1, 5, and 20, and
an admitted ResearchRun never depends on a runtime default.

One ResearchRun uses only its one immutable interval. Supporting every integer
in the range does not cause the runtime to execute or compare additional
rebalance schedules.
