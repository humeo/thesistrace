# 15 — Calculate complete Strategy metrics

**What to build:** Publish all accepted Strategy time series, events, and scalar
metrics from the one actual fill path and its Net-primary accounting state.

**Blocked by:** 14 — Handle suspension, delisting, and Strategy Benchmark.

**Status:** resolved

- [x] Gross and Net NAV retain pre- and post-trade observations from the same fills and expose deterministic Decimal residuals separately from costs.
- [x] Gross, Net, and Benchmark cumulative and 252-session CAGR values use the common baseline and actual return-interval count.
- [x] Annualized Excess Return compounds relative Net wealth rather than subtracting independent CAGRs.
- [x] Maximum Drawdown retains the full series, peak, trough, first recovery, and unrecovered state.
- [x] Annualized sample volatility, zero-risk-free-rate Sharpe, and Net CAGR Calmar follow their accepted missing-denominator rules.
- [x] Turnover retains every scheduled event including zero, plus average and annualized aggregates.
- [x] Cost amount, cost ratio, and Gross-minus-Net cumulative return drag are reported without an extra annualized drag.
- [x] Holdings Count, Maximum Single-Name Weight, Cash Ratio, and three Market Rejection categories retain required daily/event detail and aggregates.

## Comments

- Added complete Gross, Net, benchmark, drawdown, risk, turnover, cost,
  deployment, concentration, and rejection reporting from the single fill
  path.
- Daily observations retain pre/post NAV, returns, costs, holdings, cash,
  valuation events, and deterministic accounting residuals.
- Historical note: ADR-0147 and the Bounded Research Storage Spec replace the
  original event-retention boundary. The complete Strategy Daily Observation
  series and bounded aggregates remain durable, while raw orders, child orders,
  fills, and rejection-event details are execution intermediates.
