import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  ResearchFolderLoadFailure,
  ResearchOrganizationPanel,
  ResearchRunProgressView,
  ResearchRunHistory,
  TerminalStrategyStateView,
  UseAsDraftPanel,
  isTerminalResearch,
  type TerminalStrategyState,
} from "./ResearchRunsPage";

describe("ResearchRunProgressView", () => {
  it("separates committed warm-up and Research progress from in-flight work", () => {
    const markup = renderToStaticMarkup(
      <ResearchRunProgressView
        active
        progress={{
          phase: "research",
          completed_warmup_sessions: 252,
          total_warmup_sessions: 252,
          completed_research_sessions: 126,
          total_research_sessions: 4034,
          committed_chunk_count: 6,
          last_completed_warmup_session: "2010-12-31",
          last_completed_research_session: "2011-06-30",
          remaining_duration_estimate_seconds: 840,
          duration_is_estimate: true,
        }}
      />,
    );
    expect(markup).toContain("Committed progress");
    expect(markup).toContain("Warm-up 252 / 252");
    expect(markup).toContain("Research 126 / 4034");
    expect(markup).toContain("in flight and not yet committed");
    expect(markup).toContain("revisable estimate, not an SLA");
    expect(markup).not.toMatch(/checkpoint|staged|payload|alpha value/i);
  });
});

describe("ResearchFolderLoadFailure", () => {
  it("keeps Folder recovery separate from ResearchRun loading", () => {
    const markup = renderToStaticMarkup(
      <ResearchFolderLoadFailure error="Research Folders unavailable" onRetry={() => undefined} />,
    );
    expect(markup).toContain("Research Folders unavailable");
    expect(markup).toContain("Retry Folders");
    expect(markup).not.toContain("ResearchRun unavailable");
  });
});

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
        research_kind: "factor_evaluation" as const,
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
        research_kind: "strategy_backtest" as const,
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

describe("ResearchOrganizationPanel", () => {
  it("offers mutable name and Folder controls without Run or Draft recreation", () => {
    const markup = renderToStaticMarkup(
      <ResearchOrganizationPanel
        folders={[
          { id: "folder_default", name: "Default", is_default: true },
          { id: "folder_signals", name: "Signals", is_default: false },
        ]}
        onOrganized={() => undefined}
        run={{
          id: "run_aaaaaaaa",
          status: "succeeded",
          name: "Duplicate",
          folder_id: "folder_default",
          created_at: "2026-08-13T01:02:03Z",
          start_date: "2026-08-01",
          end_date: "2026-08-05",
          formula_summary: "close_adj",
          research_kind: "strategy_backtest",
        }}
      />,
    );
    expect(markup).toContain("Research name");
    expect(markup).toContain("Research Folder");
    expect(markup).toContain("Signals");
    expect(markup).toContain("Update organization");
    expect(markup).not.toMatch(/Draft|Rerun|Revision/);
  });
});

describe("UseAsDraftPanel", () => {
  it("is available for every terminal Research state only", () => {
    expect(isTerminalResearch("succeeded")).toBe(true);
    expect(isTerminalResearch("failed")).toBe(true);
    expect(isTerminalResearch("cancelled")).toBe(true);
    expect(isTerminalResearch("queued")).toBe(false);
    expect(isTerminalResearch("running")).toBe(false);
    expect(isTerminalResearch("cancelling")).toBe(false);
  });

  it("offers explicit local reuse without a Rerun action", () => {
    const markup = renderToStaticMarkup(
      <UseAsDraftPanel
        folders={[{ id: "folder_default", name: "Default", is_default: true }]}
        input={{
          formula: "close_adj",
          hypothesis: null,
          start_date: "2026-08-01",
          end_date: "2026-08-05",
          universe: "top300",
          neutralization: "none",
          research_kind: "strategy_backtest",
          holdings_count: 10,
          rebalance_every_sessions: 2,
        }}
        confirmDiscard={() => true}
        navigate={() => undefined}
        sourceFolderId="folder_default"
        storage={{ getItem: () => null, setItem: () => undefined }}
      />,
    );
    expect(markup).toContain("Use as Draft");
    expect(markup).toContain("Target Folder");
    expect(markup).not.toMatch(/Rerun|Run now/);
  });
});
