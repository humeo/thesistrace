---
status: accepted
---

# Apply board-specific A-share order-quantity rules

V1 represents orders in integer Execution Shares. For a buy, it divides the
Target Portfolio value deficit by the instrument's Raw Market Price open. For a
partial sell intended to remove research value `E`, it uses the dual-unit
conversion from ADR-0070:

```text
unrounded sell quantity =
    current Execution Share Quantity * E / current Position Value
```

V1 then rounds down under the applicable board rule. A buy cannot exceed its
target deficit or available Net Cash; a partial sell cannot exceed its target
value reduction.

For Shanghai and Shenzhen main-board shares and ChiNext shares, a buy and a
partial sell use multiples of 100 shares. For STAR Market shares, a buy requires
at least 200 shares and may increase in one-share increments after reaching 200;
a partial sell order also requires at least 200 shares. A complete liquidation
on any supported board sells the entire remaining Execution Share Quantity in
one logical order, including an otherwise non-standard odd-lot remainder. An
existing main-board or ChiNext odd-lot remainder is retained until complete
liquidation rather than split across partial sells.

An order whose rounded quantity is below its applicable minimum is not created,
and the corresponding capital remains in its current position or cash.
ResearchRun retains the unrounded target quantity, legal order quantity, and
residual position value or cash. Execution Share Quantity is never fractional;
Adjusted Holding Units may be fractional by definition.

ADR-0051 defines maximum single-order quantities and resulting child orders.
