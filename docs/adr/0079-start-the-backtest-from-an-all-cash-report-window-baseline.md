---
status: accepted
---

# Start the Backtest from an all-cash Research Window baseline

Let `R1` through `R504` be the ordered Research Sessions in the reported
Research Window. At the `R1` open, before any Strategy execution, V1 records
one common baseline:

```text
Gross NAV     = CNY 10,000,000
Net NAV       = CNY 10,000,000
Benchmark NAV = 1
Actual Holdings = empty
```

The calculation-only warm-up may supply historical inputs to the Alpha
Expression but none of its Alpha Values may create Strategy orders. The first
Strategy signal is the Final Alpha Cross-Section produced after `R1` closes,
and its first deployment is attempted at the `R2` open.

The first reported return interval is therefore `R1` open to `R2` open. There
is no prior holding return: Gross Return and Benchmark Return are zero, while
Net Return includes the Transaction Costs of the initial deployment at `R2`.
The first Strategy holding return and corresponding Benchmark market return
run from the `R2` open to the `R3` open.

This common baseline prevents a warm-up signal from entering the report and
ensures initial deployment costs are included rather than deducted before the
reported Net NAV series begins.

ADR-0104 uses this `R1` baseline as the fixed Tracking Origin for a DailyTrack
seeded from the successful ResearchRun. Activation continues from the seed's
terminal accounting state and never creates another CNY 10,000,000 baseline.
