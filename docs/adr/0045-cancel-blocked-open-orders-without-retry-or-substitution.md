---
status: accepted
---

# Cancel blocked open orders without retry or substitution

Every V1 Strategy order is valid only for its scheduled execution open. If the
Open Execution Model blocks it, the runtime cancels it immediately:

- a blocked buy leaves its capital as cash and does not substitute the
  next-ranked instrument;
- a blocked sell leaves the existing position unchanged; and
- neither side is queued or retried on a non-rebalance session.

At the next scheduled Rebalance, Strategy starts from the actual retained
positions and cash, consumes the new scheduled Alpha snapshot, and calculates a
new complete target. If the new target still requires the prior trade, it
creates a new order then. ADR-0067 defines the reported rejection reasons.
