# 03 — Add the compact Result Bundle projection

**What to build:** Let a research author run and reopen the same Factor and
Strategy report from a compact retained-result projection, while legacy result
objects remain temporarily hidden only to keep existing DailyTrack consumers
working until the contract step.

**Blocked by:** 01 — Write deterministic Parquet Physical Data Objects.

**Status:** resolved

- [x] A successful ResearchRun publishes bounded Factor summaries and Strategy summary, Strategy Daily Observations, Rebalance and execution aggregates, Terminal Positions, Terminal Strategy State, and bounded provenance and diagnostic summaries in their specified JSON or Parquet forms.
- [x] Each retained ResearchRun table uses one Parquet object rather than one object per Research Session, and its declared schema contains only the fields required by the retained product boundary.
- [x] Strategy Daily Observations retain only Research Session, Gross NAV, Net NAV, Benchmark NAV, Net Cash, session Transaction Costs, Actual Holdings Count, Maximum Single-Name Weight, and the three Market Rejection counts.
- [x] The Result API reconstructs every confirmed Factor summary and Strategy metric exactly from the compact retained boundary.
- [x] Strategy NAV, Benchmark, drawdown, Turnover, holdings, concentration, cash, cost, and rejection-count views remain available; Cash Ratio, Drawdown, and other redundant series are derived by the API from retained authoritative fields rather than stored again.
- [x] Daily Factor curves, recent fill and rejection details, execution-event tables, and raw Result artifact download controls are absent from the Web report.
- [x] The Web reads authoritative API projections and does not independently calculate Factor or Strategy domain results.
- [x] The compact Terminal Strategy State contains all positions, cash, NAV, cumulative costs, Rebalance phase, and bounded pending signal state required to seed Daily Tracking.
- [x] Pre-trade snapshots, valuation events, target histories, and other growing diagnostics remain transient rather than being copied wholesale into a Parquet replacement for the legacy Strategy object.
- [x] Legacy Alpha, Label, full Factor, and raw Strategy objects remain migration-only compatibility objects, are not exposed as product results, and gain no new consumer before ticket 06 removes them.
- [x] Failed or cancelled Runs expose no successful compact Result Bundle or partial report.

## Comments

- Added a compact Result projection with four one-object Parquet tables
  (`strategy_daily_observations`, `rebalance_aggregates`,
  `execution_aggregates`, and `terminal_positions`) plus bounded JSON Factor,
  Strategy, diagnostic, and Terminal Strategy State objects.
- The Result API rehydrates only redundant Strategy series from the retained
  daily and rebalance tables. Acceptance compares every returned Factor summary
  and Strategy metric against the same calculation's temporary compatibility
  objects exactly.
- The Web no longer renders or references daily Factor curves, recent
  fill/rejection details, raw event tables, or artifact-download controls.
  Strategy NAV, benchmark, drawdown, turnover, holdings, concentration, and
  cash views remain API-backed.
- Fixture capacity evidence: compact objects total `41,925` bytes, including
  `26,837` bytes for all 504 Strategy Daily Observations. The temporary
  compatibility objects total `19,486,415` bytes and remain hidden under the
  private `compatibility_objects` manifest index until ticket 06 removes them.
- Verification: full backend suite `50 passed`; focused ResearchRun,
  DailyTrack, and Parquet regressions `9 passed`; `uv run ruff check .`; `bun
  run typecheck`; and `bun run build`.
