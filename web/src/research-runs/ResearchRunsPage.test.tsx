import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  ResearchRunHistory,
  TerminalStrategyStateView,
  type TerminalStrategyState,
} from "./ResearchRunsPage";

const TERMINAL_STATE: TerminalStrategyState = {
  session: "2026-08-05",
  gross_cash: "9000000",
  net_cash: "8999995",
  gross_nav: "10001000",
  net_nav: "10000995",
  benchmark_nav: "1.001",
  cumulative_transaction_cost: "5",
  positions: [
    {
      instrument_id: "cn.stock.000001",
      execution_shares: 100,
      adjusted_units: "100",
      last_adjusted_price: "10.01",
    },
  ],
  rebalance_phase: {
    origin_session: "2026-08-03",
    report_session_count: 3,
    rebalance_interval: 1,
    completed_intervals: 2,
  },
  pending_signal: {
    signal_session: "2026-08-05",
    execution: "next_research_session_open",
  },
};

describe("TerminalStrategyStateView", () => {
  it("renders the retained terminal account and holdings", () => {
    const markup = renderToStaticMarkup(
      <TerminalStrategyStateView state={TERMINAL_STATE} />,
    );

    expect(markup).toContain("Terminal Strategy State");
    expect(markup).toContain("2026-08-05");
    expect(markup).toContain("10000995");
    expect(markup).toContain("8999995");
    expect(markup).toContain("cn.stock.000001");
    expect(markup).toContain("remains pending");
    expect(markup).not.toMatch(/Generation|manifest|checkpoint|fence|object location/i);
  });
});

describe("ResearchRunHistory", () => {
  it("distinguishes duplicate names by identity, time, status, and Formula", () => {
    const items = [
      {
        id: "run_aaaaaaaa",
        status: "succeeded" as const,
        name: "Mean",
        folder_id: "folder_default",
        created_at: "2026-08-13T01:02:03Z",
        start_date: "2026-08-01",
        end_date: "2026-08-05",
        formula_summary: "ts_mean(close_adj, 20)",
      },
      {
        id: "run_bbbbbbbb",
        status: "queued" as const,
        name: "Mean",
        folder_id: "folder_default",
        created_at: "2026-08-13T01:03:04Z",
        start_date: "2026-08-01",
        end_date: "2026-08-05",
        formula_summary: "ts_mean(close_adj, 60)",
      },
    ];

    const markup = renderToStaticMarkup(<ResearchRunHistory items={items} />);
    expect(markup).toContain("run_aaaaaaaa");
    expect(markup).toContain("run_bbbbbbbb");
    expect(markup).toContain("2026-08-13T01:02:03Z");
    expect(markup).toContain("succeeded");
    expect(markup).toContain("ts_mean(close_adj, 20)");
    expect(markup.match(/>Mean</g)).toHaveLength(2);
  });
});
