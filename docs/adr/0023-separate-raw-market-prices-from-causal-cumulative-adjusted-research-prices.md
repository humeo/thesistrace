---
status: accepted
---

# Separate Raw Market Prices from causal cumulative-adjusted Research Prices

ThesisTrace retains the complete accepted eleven-field Tushare `daily` response
and the separate `adj_factor` response as authoritative source facts. ADR-0071 maps
their source names and units to normalized Canonical fields. It does not
persist Tushare qfq or hfq histories as additional source facts. Adjusted
fields are deterministic derivatives that a Data Generation can reproduce from
its retained raw prices and factors.

For instrument `i` and retained session `t`:

```text
adjustment_scale(i,t) = A(i,t)
P_adj(i,t)            = P_raw(i,t) * adjustment_scale(i,t)
```

The same session scale is applied to raw open, high, low, and close. This is
the cumulative adjustment formula that
[Tushare documents as `hfq`](https://tushare.pro/document/2?doc_id=146), but
ThesisTrace derives the values from its retained Canonical source facts rather
than fetching a vendor-adjusted history.

Every adjusted row depends only on the raw price and Source Adjustment Factor
at that row's session. Adding a later factor therefore never rescales an
existing adjusted price or changes a historical absolute-price Alpha. There is
no Adjustment Anchor, latest-factor reference, or per-row reference factor.
The adjusted coordinate is not a quoted execution price and does not force the
latest adjusted row to equal the latest Raw Market Price.

## Why the latest-session denominator is rejected

The previous implementation replaced a fixed first-valid post-listing anchor
with Tushare's documented qfq convention: divide every retained factor by the
factor at the Data Generation's latest retained session. It was chosen because
it removed the expensive per-instrument anchor search, made the latest adjusted
quote equal the latest raw quote, and left within-instrument return ratios
unchanged.

That qfq reference is a future, instrument-specific scaling constant for every
earlier signal. It cancels from return ratios, but it does not cancel from
absolute-price expressions such as `delta(adjusted_price, 1)`. Extending a Data
Generation could therefore change historical Alpha ranks, selections, and
backtests. The sole Canonical contract rejects that trade-off and keeps the
no-anchor collection path while using only same-session factors.

Price-based Alphas, multi-session returns, future-return labels, and the
Strategy Benchmark use Adjusted Research Prices. Quoted-price execution
conditions, exchange price limits, Transaction Cost notional, and Board-Lot
Rounding use Raw Market Prices and integer Execution Share Quantities.
ADR-0070 defines the conversion between those execution quantities and
Adjusted Holding Units, including the distinct buy and sell sizing rules.

Absolute-price Alpha expressions such as `delta(adjusted_price, 1)` remain
price-level-sensitive across instruments even though they are future-invariant.
Research authors should use `pct_change` or another dimensionless expression
when they intend to compare returns rather than absolute adjusted-price moves.

After source-unit normalization, `volume_shares` and `turnover_amount_cny` are
never adjustment-rescaled. Strategy Backtest accrues holding returns from
Adjusted Research Prices without consuming separate company-action events. Its
resulting positions are synthetic research positions rather than broker share
balances. Strategy rebalance frequency remains a separate Research Definition
decision.
