---
status: accepted
---

# Separate Raw Market Prices from fixed-anchor Adjusted Research Prices

V1 retains the complete accepted eleven-field Tushare `daily` response and the
separate `adj_factor` response as authoritative source facts. ADR-0071 maps
their source names and units to normalized Canonical fields. It does not
persist Tushare qfq and hfq histories as additional facts. Adjusted fields are
deterministic derivatives that a Dataset Release can reproduce from those
inputs.

For each instrument, ADR-0073 fixes anchor session `b` as the first post-listing
session with both a valid raw daily bar and Source Adjustment Factor. Dataset
Release owns the immutable Adjustment Anchor and reuses it when later releases
append data or the Research Window advances. With raw close `P_raw(i,b)` and
Source Adjustment Factor `A(i,b)` at the anchor:

```text
adjustment_scale(i,t) = A(i,t) / A(i,b)
P_adj(i,t)            = P_raw(i,t) * adjustment_scale(i,t)
```

The same session factor is applied to raw open, high, low, and close. The
Adjustment Scale is `1` at the anchor, so the Adjusted Research Price initially
equals the Raw Market Price. Appending future sessions never moves the anchor
or rescales existing history. A source correction is incorporated into the
next immutable new-session Dataset Release rather than changing an earlier one
or producing a correction-only release.

Price-based Alphas, multi-session returns, future-return labels, and the
Strategy Benchmark use Adjusted Research Prices. Quoted-price execution
conditions, exchange price limits, Transaction Cost notional, and Board-Lot
Rounding use Raw Market Prices and integer Execution Share Quantities.
ADR-0070 defines the conversion between those execution quantities and
Adjusted Holding Units, including the distinct buy and sell sizing rules.

After source-unit normalization, `volume_shares` and
`turnover_amount_cny` are never adjustment-rescaled. Strategy Backtest accrues
holding returns from Adjusted Research Prices without consuming separate
company-action events. Its resulting positions are synthetic research positions
rather than broker share balances. Strategy rebalance frequency remains a
separate Research Definition decision.
