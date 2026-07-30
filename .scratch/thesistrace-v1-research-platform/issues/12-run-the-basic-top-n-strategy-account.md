# 12 — Run the basic Top-N Strategy Account

**What to build:** Execute the fixed long-only Top-N equal-weight Strategy from
the all-cash Research Window baseline through deterministic scheduled Open NAV
Cycles.

**Blocked by:** 04 — Publish Calendar, Universe, Industry, and Field Catalog; 08 — Fix numeric execution and canonical serialization; 09 — Evaluate Alpha Expressions and Alpha Matrices.

**Status:** ready-for-agent

- [ ] The account begins at the first report-window Open with CNY 10,000,000, no holdings, and Benchmark NAV 1.
- [ ] Warm-up Alpha never creates an order; the first report-window close creates the first eligible signal.
- [ ] Rebalance Interval supports every integer from 1 through 20 and preserves one fixed phase.
- [ ] Candidates order by descending final Alpha then ascending Instrument Identity and select at most the explicit 1-to-100 Holdings Count.
- [ ] Pre-trade Net NAV sets equal target values; sells occur before buys and every decision uses Net state.
- [ ] Integer Execution Shares and fractional Adjusted Holding Units evolve through one deterministic account state.
- [ ] The final finite ResearchRun Open values holdings without forced liquidation or a terminal Rebalance.
