export const completedStrategyRun = {
  id: "run_evidence", status: "succeeded", name: "Evidence <br/> & regression",
  folder_id: "folder_default", created_at: "2026-09-15T00:00:00Z",
  start_date: "2026-08-03", end_date: "2026-08-04", formula_summary: "rank(-pb)",
  research_kind: "strategy_backtest",
  result: {
    strategy: {
      summary: { alpha_checksum: "a", source_checksum: "b", entry_session: "2026-08-04", initial_cash_cny: "100000",
        metrics: { net_cumulative_return: 0, benchmark_cumulative_return: null, benchmark_cagr: null,
          annualized_excess_return: null, maximum_drawdown: { value: 0 }, sharpe: null, transaction_costs: { ratio: 0 } } },
      observations: [], comparison: { status: "unavailable", reason: "benchmark_snapshot_unavailable" },
    },
    terminal_strategy_state: {
      close_risk_nav_cny: "100000",
      session: "2026-08-04", net_cash: "100000", gross_cash: "100000", net_nav: "100000", gross_nav: "100000",
      cumulative_transaction_cost: "0", positions: [], pending_target: null, contract_checksum: "contract",
      decision_state: { mode: "framework", selection: { signal_session: "2026-08-03", eligibility_exclusions: {} }, selection_interval: 10, exposure: 1 },
      research_phase: { origin_session: "2026-08-03", report_session_count: 2 },
    },
    provenance: { schema_version: "research-result-v3", research_run_id: "run_evidence", immutable_input_sha256: "a".repeat(64),
      calculation_contracts: {}, semantic_versions: {}, research_kind: "strategy_backtest" },
  },
};
