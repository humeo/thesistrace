# 15 — Calculate complete Strategy metrics

**What to build:** Publish all accepted Strategy time series, events, and scalar
metrics from the one actual fill path and its Net-primary accounting state.

**Blocked by:** 14 — Handle suspension, delisting, and Strategy Benchmark.

**Status:** ready-for-agent

- [ ] Gross and Net NAV retain pre- and post-trade observations from the same fills and expose deterministic Decimal residuals separately from costs.
- [ ] Gross, Net, and Benchmark cumulative and 252-session CAGR values use the common baseline and actual return-interval count.
- [ ] Annualized Excess Return compounds relative Net wealth rather than subtracting independent CAGRs.
- [ ] Maximum Drawdown retains the full series, peak, trough, first recovery, and unrecovered state.
- [ ] Annualized sample volatility, zero-risk-free-rate Sharpe, and Net CAGR Calmar follow their accepted missing-denominator rules.
- [ ] Turnover retains every scheduled event including zero, plus average and annualized aggregates.
- [ ] Cost amount, cost ratio, and Gross-minus-Net cumulative return drag are reported without an extra annualized drag.
- [ ] Holdings Count, Maximum Single-Name Weight, Cash Ratio, and three Market Rejection categories retain required daily/event detail and aggregates.
