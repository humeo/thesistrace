---
status: accepted
---

# Split logical orders at board-specific single-order limits

After Board-Lot Rounding, V1 splits a logical order whose quantity exceeds its
board's limit-order quantity cap into legal child orders:

```text
Shanghai and Shenzhen main boards: 1,000,000 shares
ChiNext:                             300,000 shares
STAR Market:                         100,000 shares
```

Every child observes the board's minimum and increment rules. All child orders
for one instrument share the same synthetic next-open price and eligibility
result. If `full_session_suspended` leaves no daily open or the applicable price
limit blocks the instrument, none of its children fill; otherwise every child
fills completely. A partial-session suspension with a later valid daily open
uses that open under ADR-0089. Unknown or invalid open data fails under
ADR-0074 before Child Order execution.

Transaction Costs, including minimum commission, apply to each child
separately. Splitting does not introduce partial fills, volume capacity, market
impact, or slippage.
