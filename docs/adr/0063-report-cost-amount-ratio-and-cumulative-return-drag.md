---
status: accepted
---

# Report cost amount, ratio, and Cumulative Return drag

V1 reports three Transaction Cost attribution values from the one Actual
Holdings and fill path:

```text
Cumulative Transaction Costs =
    sum(cost of every filled child order)

Transaction Cost Ratio =
    Cumulative Transaction Costs / Initial Cash

Transaction Cost Return Drag =
    Gross Cumulative Return - Net Cumulative Return
```

Transaction Cost Return Drag is the primary user-facing cost-loss metric and is
reported as a percentage-point difference. It is not a percentage of current
NAV or the relative percentage decrease from Gross Return to Net Return.

Because Gross and Net Annualized Return are already reported separately, V1
does not add a duplicate annualized cost-drag metric.
