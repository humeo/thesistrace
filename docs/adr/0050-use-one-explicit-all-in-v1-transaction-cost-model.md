---
status: accepted
---

# Use one explicit all-in V1 Transaction Cost model

Every V1 Research Definition explicitly records the following fixed values:

```yaml
costs:
  commission_rate_all_in: 0.0003
  commission_min_cny: 5
  stamp_duty_sell_rate: 0.0005
  transfer_fee_rate: 0.00001
```

For each filled order, including each child order defined by ADR-0051, with Raw
Market Price notional `V`, commission is `max(V * 0.0003, CNY 5)`. A buy costs
commission plus `V * 0.00001`; a sell costs commission plus `V * 0.00001` plus
`V * 0.0005`. Costs are deducted from cash, and buy sizing must leave cash
non-negative.

For a sell, `V` remains the cost and execution-constraint base even when the
synthetic Research Settlement defined by ADR-0070 differs from Raw Market Price
notional.

The 0.0003 broker commission is a V1 all-in product assumption, not a universal
statutory rate. Regulatory and exchange handling fees are treated as included
in that all-in commission and are not deducted again. The stamp-duty and
transfer-fee assumptions are recorded separately. A future cost change requires
a new versioned definition rather than changing an existing ResearchRun.

ADR-0094 calculates these formulas with decimal arithmetic without rounding
each filled order or Child Order's fees to CNY 0.01. Two-decimal report
formatting does not alter accounting state.
