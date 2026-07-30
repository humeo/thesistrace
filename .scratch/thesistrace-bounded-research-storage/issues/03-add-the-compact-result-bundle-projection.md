# 03 — Add the compact Result Bundle projection

**What to build:** Let a research author run and reopen the same Factor and
Strategy report from a compact retained-result projection, while legacy result
objects remain temporarily hidden only to keep existing DailyTrack consumers
working until the contract step.

**Blocked by:** 01 — Write deterministic Parquet Physical Data Objects.

**Status:** ready-for-agent

- [ ] A successful ResearchRun publishes bounded Factor summaries and Strategy summary, Strategy Daily Observations, Rebalance and execution aggregates, Terminal Positions, Terminal Strategy State, and bounded provenance and diagnostic summaries in their specified JSON or Parquet forms.
- [ ] Each retained ResearchRun table uses one Parquet object rather than one object per Research Session, and its declared schema contains only the fields required by the retained product boundary.
- [ ] Strategy Daily Observations retain only Research Session, Gross NAV, Net NAV, Benchmark NAV, Net Cash, session Transaction Costs, Actual Holdings Count, Maximum Single-Name Weight, and the three Market Rejection counts.
- [ ] The Result API reconstructs every confirmed Factor summary and Strategy metric exactly from the compact retained boundary.
- [ ] Strategy NAV, Benchmark, drawdown, Turnover, holdings, concentration, cash, cost, and rejection-count views remain available; Cash Ratio, Drawdown, and other redundant series are derived by the API from retained authoritative fields rather than stored again.
- [ ] Daily Factor curves, recent fill and rejection details, execution-event tables, and raw Result artifact download controls are absent from the Web report.
- [ ] The Web reads authoritative API projections and does not independently calculate Factor or Strategy domain results.
- [ ] The compact Terminal Strategy State contains all positions, cash, NAV, cumulative costs, Rebalance phase, and bounded pending signal state required to seed Daily Tracking.
- [ ] Pre-trade snapshots, valuation events, target histories, and other growing diagnostics remain transient rather than being copied wholesale into a Parquet replacement for the legacy Strategy object.
- [ ] Legacy Alpha, Label, full Factor, and raw Strategy objects remain migration-only compatibility objects, are not exposed as product results, and gain no new consumer before ticket 06 removes them.
- [ ] Failed or cancelled Runs expose no successful compact Result Bundle or partial report.
