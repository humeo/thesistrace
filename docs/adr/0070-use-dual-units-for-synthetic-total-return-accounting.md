---
status: accepted
---

# Use dual units for synthetic total-return accounting

V1 represents each Strategy position with two quantities:

```text
Q = Execution Share Quantity
U = Adjusted Holding Units
S(t) = Adjusted Research Price(t) / Raw Market Price(t)
Position Value(t) = U * Adjusted Research Price(t)
```

`Q` is a non-negative integer changed only by filled orders. It is used for
Board-Lot Rounding, Child Orders, order caps, and Raw Market Price notional.
`U` may be fractional and is used only for research valuation. It does not
represent shares in a broker account.

For a filled buy of `q` Execution Shares at session `t`:

```text
Raw Notional = q * Raw Market Price(t)
Added Adjusted Holding Units = q / S(t)

Q_after = Q_before + q
U_after = U_before + q / S(t)
Gross Cash after = Gross Cash before - Raw Notional
Net Cash after = Net Cash before - Raw Notional - Transaction Costs
```

In the real-number model,
`(q / S(t)) * Adjusted Research Price(t) = Raw Notional`, so execution has no
economic Gross NAV gain or loss. V1 actually evaluates every primitive
division, multiplication, addition, and subtraction under ADR-0109's finite
`accounting_decimal_v1` context. The canonical stored values may therefore
produce a tiny deterministic accounting-rounding residual at an execution
instant. V1 does not add a balancing account or alter Raw Notional to force the
real-number identity after rounding. Buy sizing uses Net Cash and cannot make
it negative.

Between opens, both `Q` and `U` remain unchanged. Position Value changes only
through Adjusted Research Price return or an allowed Valuation Carry. This
captures Tushare-supported total-return adjustment without ingesting separate
company-action cash or share events.

For a filled partial sell of `q` Execution Shares:

```text
Removed Adjusted Holding Units =
    U_before * q / Q_before

Research Settlement =
    Removed Adjusted Holding Units * Adjusted Research Price(t)

Raw Notional =
    q * Raw Market Price(t)
```

V1 decreases `Q` by `q`, decreases `U` by the removed units, adds Research
Settlement to Gross Cash, and adds Research Settlement minus Transaction Costs
to Net Cash. A complete liquidation removes all remaining `Q` and `U`.
Transaction Costs use Raw Notional. Price-limit eligibility uses Raw Market
Price and point-in-time trading state. Order caps and Board-Lot Rounding use
Execution Shares. None of them replaces Research Settlement.

The same decimal rule applies to proportional-unit removal, Research
Settlement, remaining Position Value, and cash updates. Their real-number
conservation identity may likewise have a deterministic last-digit residual.
That residual is derivable from the checksummed pre- and post-execution state;
it is neither Transaction Cost nor a separate order, fill, or cash flow.

When reducing a position by desired research value `E`, the unrounded sell
quantity is:

```text
q_target = Q_before * E / Position Value(t)
```

Board-Lot Rounding then produces a legal integer sell quantity. This is
different from buy sizing, which converts a cash deficit through Raw Market
Price.

The two NAV views use the same `Q`, `U`, and filled orders:

```text
Gross NAV = Gross Cash + sum(Position Value)
Net NAV   = Net Cash   + sum(Position Value)
```

In the real-number model, their difference is cumulative Transaction Costs.
Both views share the same holdings and execution-rounding residual, while
independent finite decimal cash accumulation may leave a last-digit numeric
difference from that conceptual identity. V1 reports the separately
accumulated Transaction Costs and does not relabel a numeric residual as cost.

Sale cash can differ from `Q sold * Raw Market Price` because Research
Settlement realizes the Adjusted Research Price total return. V1 is therefore
a synthetic research account, not a reconstruction of broker cash proceeds.
Achieving broker-exact cash and share balances would require separate
company-action events and is outside V1. This accounting conversion is native
to ThesisTrace and does not introduce Qlib or a Qlib Provider.
