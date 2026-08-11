---
status: accepted
---

# Separate Raw Market Prices from dynamic front-adjusted Research Prices

V1 retains the complete accepted eleven-field Tushare `daily` response and the
separate `adj_factor` response as authoritative source facts. ADR-0071 maps
their source names and units to normalized Canonical fields. It does not
persist Tushare qfq or hfq histories as additional source facts. Adjusted
fields are deterministic derivatives that a Data Generation can reproduce from
its retained raw prices and factors.

For instrument `i`, let `r` be its latest session with a retained raw daily bar
and valid Source Adjustment Factor in the selected Data Generation. For any
retained session `t`:

```text
adjustment_scale(i,t) = A(i,t) / A(i,r)
P_adj(i,t)            = P_raw(i,t) * adjustment_scale(i,t)
```

The same session scale is applied to raw open, high, low, and close. The latest
available row has scale `1`, so its Adjusted Research Price equals its Raw
Market Price. There is no Adjustment Anchor record or per-row anchor factor.

When a refresh adds a later factor, the candidate Data Generation recomputes
adjusted OHLC for all retained price rows of that instrument using the new
reference. Historical adjusted price levels may therefore be rescaled between
Data Generations, while returns and corporate-action continuity within one
Generation remain coherent. An already completed ResearchRun still reads the
Data Generation it pinned.

Price-based Alphas, multi-session returns, future-return labels, and the
Strategy Benchmark use Adjusted Research Prices. Quoted-price execution
conditions, exchange price limits, Transaction Cost notional, and Board-Lot
Rounding use Raw Market Prices and integer Execution Share Quantities.
ADR-0070 defines the conversion between those execution quantities and
Adjusted Holding Units, including the distinct buy and sell sizing rules.

After source-unit normalization, `volume_shares` and `turnover_amount_cny` are
never adjustment-rescaled. Strategy Backtest accrues holding returns from
Adjusted Research Prices without consuming separate company-action events. Its
resulting positions are synthetic research positions rather than broker share
balances. Strategy rebalance frequency remains a separate Research Definition
decision.
