import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
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
