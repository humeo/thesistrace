import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  ResearchFolderLoadFailure,
  ResearchDeleteDialog,
  ResearchOrganizationPanel,
  ResearchResultView,
  ResearchRunBackLink,
  ResearchRunFacts,
  ResearchRunProgressView,
  ResearchRunHistory,
  ResearchRunPagination,
  UseAsDraftPanel,
  formatResearchRunCreatedAt,
  isTerminalResearch,
  researchRunListPath,
  sortResearchRuns,
  type ResearchResult,
  type ResearchRun,
  type TerminalStrategyState,
} from "./ResearchRunsPage";

describe("ResearchRunBackLink", () => {
  it("returns a ResearchRun detail to the Research Runs list", () => {
    const markup = renderToStaticMarkup(<ResearchRunBackLink />);

    expect(markup).toContain('href="/research-runs"');
    expect(markup).toContain("Back to Research Runs");
  });
});

describe("ResearchDeleteDialog", () => {
  it("renders an explicit in-page decision with the permanent and retained effects", () => {
    const markup = renderToStaticMarkup(
      <ResearchDeleteDialog
        deleting={false}
        error={null}
        name="Deletion dialog regression"
        onConfirm={() => undefined}
        onDismiss={() => undefined}
        open
      />,
    );

    expect(markup).toContain("<dialog");
    expect(markup).toContain('aria-modal="true"');
    expect(markup).toContain("Delete Research?");
    expect(markup).toContain("Deletion dialog regression");
    expect(markup).toContain("This cannot be undone.");
    expect(markup).toContain("DailyTracks will remain.");
    expect(markup).toContain("Keep Research");
  });
});

const STRATEGY_RUN: ResearchRun = {
  id: "run_conditions",
  status: "succeeded",
  name: "Execution conditions",
  folder_id: "folder_default",
  created_at: "2026-08-13T01:02:03Z",
  start_date: "2026-08-01",
  end_date: "2026-08-05",
  formula_summary: "ts_mean(close, 2)",
  research_kind: "strategy_backtest",
  input: {
    formula: "ts_mean(close, 2)",
    hypothesis: null,
    start_date: "2026-08-01",
    end_date: "2026-08-05",
    universe: "top300",
    neutralization: "industry",
    research_kind: "strategy_backtest",
    holdings_count: 10,
    rebalance_every_sessions: 2,
  },
};

describe("ResearchRunFacts", () => {
  it("shows the frozen Strategy execution conditions in user language", () => {
    const markup = renderToStaticMarkup(<ResearchRunFacts run={STRATEGY_RUN} />);

    expect(markup).toContain('aria-label="Research execution conditions"');
    expect(markup).toContain("<strong>Universe</strong> Top 300");
    expect(markup).toContain("<strong>Neutralization</strong> Industry");
    expect(markup).toContain("<strong>Holdings count</strong> 10");
    expect(markup).toContain("<strong>Rebalance</strong> Every 2 sessions");
  });

  it("omits Strategy-only conditions from a Factor Evaluation", () => {
    const markup = renderToStaticMarkup(
      <ResearchRunFacts
        run={{
          ...STRATEGY_RUN,
          research_kind: "factor_evaluation",
          input: {
            formula: "close",
            hypothesis: null,
            start_date: "2026-08-01",
            end_date: "2026-08-05",
            universe: "top1000",
            neutralization: "none",
            research_kind: "factor_evaluation",
          },
        }}
      />,
    );

    expect(markup).toContain("<strong>Universe</strong> Top 1000");
    expect(markup).toContain("<strong>Neutralization</strong> None");
    expect(markup).not.toContain("Holdings count");
    expect(markup).not.toContain("Rebalance");
  });
});

describe("ResearchRunProgressView", () => {
  it("separates committed warm-up and Research progress from in-flight work", () => {
    const markup = renderToStaticMarkup(
      <ResearchRunProgressView
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
        status="running"
        timing={{
          started_at: "2026-08-13T01:00:00Z",
          finished_at: null,
          elapsed_seconds: 3723,
          is_final: false,
        }}
      />,
    );
    expect(markup).toContain("Execution progress");
    expect(markup).toContain("value=\"378\"");
    expect(markup).toContain("max=\"4286\"");
    expect(markup).toContain("9%");
    expect(markup).not.toContain("252 / 252");
    expect(markup).not.toContain("Warm-up");
    expect(markup).not.toContain("Committed chunks");
    expect(markup).toContain("Research sessions");
    expect(markup).toContain("126 / 4034");
    expect(markup).toContain("1h 2m 3s");
    expect(markup).toContain("Started");
    expect(markup).toContain("2026-08-13 01:00:00 UTC");
    expect(markup).toContain("Finished");
    expect(markup).toContain("estimate may change");
    expect(markup).not.toMatch(/checkpoint|staged|payload|alpha value/i);
  });

  it("shows fixed start and finish timestamps for terminal execution", () => {
    const markup = renderToStaticMarkup(
      <ResearchRunProgressView
        progress={{
          phase: "succeeded",
          completed_warmup_sessions: 20,
          total_warmup_sessions: 20,
          completed_research_sessions: 875,
          total_research_sessions: 875,
          committed_chunk_count: 14,
          last_completed_warmup_session: "2023-01-31",
          last_completed_research_session: "2026-08-13",
          remaining_duration_estimate_seconds: null,
          duration_is_estimate: false,
        }}
        status="succeeded"
        timing={{
          started_at: "2026-08-13T01:00:00Z",
          finished_at: "2026-08-13T01:02:46Z",
          elapsed_seconds: 166,
          is_final: true,
        }}
      />,
    );

    expect(markup).toContain("Execution time");
    expect(markup).toContain("2m 46s");
    expect(markup).toContain("2026-08-13 01:00:00 UTC");
    expect(markup).toContain("2026-08-13 01:02:46 UTC");
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

describe("ResearchResultView", () => {
  it("keeps result summaries and coverage while removing low-value detail sections", () => {
    const correlation = {
      mean: 0.1,
      sample_deviation: 0,
      icir: 1,
      positive_fraction: 1,
      valid_session_count: 1,
    };
    const horizon = {
      horizon: 1 as const,
      summary: {
        ic: correlation,
        rank_ic: correlation,
        quantile_returns: { q1: null, q2: null, q3: null, q4: null, q5: null },
        top_bottom_return: null,
      },
      coverage: {
        signal_session_count: 2,
        ic_valid_session_count: 1,
        rank_ic_valid_session_count: 1,
        quantile_valid_session_count: 0,
      },
    };
    const result = {
      factor: {
        horizons: {
          "1": horizon,
          "5": { ...horizon, horizon: 5 },
          "20": { ...horizon, horizon: 20 },
        },
      },
      strategy: {
        summary: {
          alpha_checksum: "a",
          entry_session: "2026-08-03",
          initial_cash_cny: "10000000",
          source_checksum: "b",
          metrics: {
            net_cumulative_return: 0.1,
            benchmark_cumulative_return: 0.05,
            benchmark_cagr: 0.07,
            annualized_excess_return: 0.03,
            maximum_drawdown: { value: -0.02 },
            sharpe: 1.2,
            transaction_costs: { ratio: 0.0000025 },
          },
        },
        observations: [{
          session: "2026-08-03",
          gross_nav: "10000000",
          net_nav: "10000000",
          net_cash: "10000000",
          transaction_cost_cny: "0",
          holdings_count: 0,
          maximum_single_name_weight: 0,
          upper_limit_buy_rejections: 0,
          lower_limit_sell_rejections: 0,
          suspension_rejections: 0,
        }],
        comparison: {
          status: "available",
          benchmark: {
            id: "csi300-price-index-open",
            display_name: "沪深300",
            ts_code: "399300.SZ",
            kind: "price_index",
            coordinate: "open",
            snapshot_sha256: "c".repeat(64),
            coverage: {
              start_session: "2010-01-04",
              end_session: "2026-08-13",
            },
            published_at: "2026-08-13T18:00:00Z",
          },
          entry: {
            session: "2026-08-03",
            benchmark_open_level: "4000.1",
            initial_cash_cny: "10000000",
          },
          terminal: {
            session: "2026-08-05",
            benchmark_open_level: "4200.105",
            net_nav: "11000000",
          },
          metrics: {
            net_strategy_cumulative_return: 0.1,
            benchmark_cumulative_return: 0.05,
            net_strategy_cagr: 0.14,
            benchmark_cagr: 0.07,
            annualized_excess_return: 0.03,
          },
          curves: [{
            session: "2026-08-03",
            net_strategy_return: -0.001,
            benchmark_relative_return: 0,
            net_excess_nav: 0.999,
            net_excess_return: -0.001,
          }],
        },
      },
      terminal_strategy_state: TERMINAL_STATE,
      provenance: {
        schema_version: "research-result-v2",
        research_run_id: "run_test",
        immutable_input_sha256: "a".repeat(64),
        calculation_contracts: {},
        semantic_versions: { kernel: "kernel-v5" },
        research_kind: "strategy_backtest",
      },
    } satisfies ResearchResult;
    const markup = renderToStaticMarkup(<ResearchResultView result={result} />);

    expect(markup).toContain("Factor Summary");
    expect(markup).toContain("Strategy Summary");
    expect(markup).toContain("Rank IC coverage 1/2");
    expect(markup).toContain("CSI 300");
    expect(markup).not.toContain("沪深300");
    expect(markup).not.toContain("Fixed Strategy Benchmark");
    expect(markup).not.toContain("数据截至");
    expect(markup).not.toContain("c".repeat(64));
    expect(markup).not.toContain("Entry Open");
    expect(markup).not.toContain("Terminal Open");
    expect(markup).not.toContain("Net Excess");
    expect(markup).not.toContain("Final Portfolio");
    expect(markup).not.toContain("cn.stock.000001");
    expect(markup).not.toMatch(
      /Predictive evidence|One fill path|Research-period account observations|signal sessions|Daily Observations|Provenance|Input digest/i,
    );

    const unavailableMarkup = renderToStaticMarkup(
      <ResearchResultView
        result={{
          ...result,
          strategy: {
            ...result.strategy,
            comparison: {
              status: "unavailable",
              reason: "benchmark_snapshot_unavailable",
            },
          },
        }}
      />,
    );
    expect(unavailableMarkup).toContain("CSI 300 comparison unavailable");
    expect(unavailableMarkup).toContain("No comparison chart is shown");
    expect(unavailableMarkup).not.toContain("<figure");
  });
});

describe("ResearchRunHistory", () => {
  const items = [
    {
      id: "run_aaaaaaaa",
      status: "succeeded" as const,
      name: "Mean",
      folder_id: "folder_default",
      created_at: "2026-08-13T01:02:03.987654Z",
      start_date: "2026-08-01",
      end_date: "2026-08-05",
      formula_summary: "ts_mean(close, 20)",
      research_kind: "strategy_backtest" as const,
      key_metrics: {
        research_kind: "strategy_backtest" as const,
        annualized_excess_return: 0.03,
        sharpe: 1.2345,
        maximum_drawdown: 0.12,
      },
    },
    {
      id: "run_bbbbbbbb",
      status: "queued" as const,
      name: "Mean",
      folder_id: "folder_default",
      created_at: "2026-08-13T01:03:04Z",
      start_date: "2026-08-01",
      end_date: "2026-08-05",
      formula_summary: "ts_mean(close, 60)",
      research_kind: "factor_evaluation" as const,
      key_metrics: {
        research_kind: "factor_evaluation" as const,
        one_session_rank_ic: 0.031,
        five_session_rank_ic: 0.052,
        twenty_session_rank_ic: 0.018,
      },
    },
    {
      id: "run_cccccccc",
      status: "succeeded" as const,
      name: "Quality",
      folder_id: "folder_default",
      created_at: "2026-08-13T01:01:02Z",
      start_date: "2026-08-01",
      end_date: "2026-08-05",
      formula_summary: "rank(close)",
      research_kind: "strategy_backtest" as const,
      key_metrics: {
        research_kind: "strategy_backtest" as const,
        annualized_excess_return: 0.05,
        sharpe: 0.8,
        maximum_drawdown: 0.08,
      },
    },
  ];

  it("shows type-labelled summaries for a mixed Research list", () => {
    const markup = renderToStaticMarkup(<ResearchRunHistory items={items} />);

    expect(markup).toContain(">Type</th>");
    expect(markup).toContain("Factor Evaluation");
    expect(markup).toContain("Strategy Backtest");
    expect(markup).toContain("Created (UTC)");
    expect(markup).toContain(">2026-08-13 01:02:03</time>");
    expect(markup).toContain("Result summary");
    expect(markup).toContain("1S Rank IC");
    expect(markup).toContain("Excess");
    expect(markup).toContain("+3.00%");
    expect(markup).toContain("0.031");
    expect(markup).toContain("1.234");
    expect(markup).toContain("12.00%");
    expect(markup).not.toContain(">Run ID<");
    expect(markup).not.toContain(">Formula<");
    expect(markup).not.toContain("ts_mean(close, 20)");
    expect(markup.match(/>Mean</g)).toHaveLength(2);
  });

  it("uses comparable strategy metrics when the Type filter is narrowed", () => {
    const markup = renderToStaticMarkup(
      <ResearchRunHistory items={items.filter((item) => item.research_kind === "strategy_backtest")} researchKind="strategy_backtest" />,
    );

    expect(markup).toContain("Annualized excess");
    expect(markup).toContain("Sharpe");
    expect(markup).toContain("Max drawdown");
    expect(markup).not.toContain("1S Rank IC");
  });

  it("uses primary Rank IC across all Factor horizons when Type is Factor Evaluation", () => {
    const markup = renderToStaticMarkup(
      <ResearchRunHistory items={[items[1]]} researchKind="factor_evaluation" />,
    );

    expect(markup).toContain("1-session Rank IC");
    expect(markup).toContain("5-session Rank IC");
    expect(markup).toContain("20-session Rank IC");
    expect(markup).toContain("0.052");
    expect(markup).not.toContain("Annualized excess");
  });

  it("sorts metrics with unavailable values last", () => {
    expect(sortResearchRuns(items, "sharpe", "descending").map((item) => item.id)).toEqual([
      "run_aaaaaaaa",
      "run_cccccccc",
      "run_bbbbbbbb",
    ]);
    expect(
      sortResearchRuns(items, "maximum_drawdown", "ascending").map((item) => item.id),
    ).toEqual([
      "run_cccccccc",
      "run_aaaaaaaa",
      "run_bbbbbbbb",
    ]);
    expect(
      sortResearchRuns(items, "five_session_rank_ic", "descending").map((item) => item.id),
    ).toEqual([
      "run_bbbbbbbb",
      "run_aaaaaaaa",
      "run_cccccccc",
    ]);
  });

  it("formats creation timestamps in UTC through whole seconds", () => {
    expect(formatResearchRunCreatedAt("2026-08-13T09:02:03.987654+08:00")).toBe(
      "2026-08-13 01:02:03",
    );
    expect(formatResearchRunCreatedAt("invalid")).toBe("Not available");
  });
});

describe("Research Runs pagination", () => {
  it("builds a bounded, filtered cursor request", () => {
    expect(researchRunListPath({
      cursor: "cursor+/=",
      folderId: "folder signals",
      researchKind: "factor_evaluation",
    })).toBe(
      "/api/research-runs?limit=20&folder_id=folder+signals&research_kind=factor_evaluation&cursor=cursor%2B%2F%3D",
    );
  });

  it("keeps the current page and both navigation directions visible", () => {
    const markup = renderToStaticMarkup(
      <ResearchRunPagination
        hasNextPage={false}
        onNextPage={() => undefined}
        onPreviousPage={() => undefined}
        pageIndex={1}
      />,
    );

    expect(markup).toContain("Page 2");
    expect(markup).toContain("Previous");
    expect(markup).toContain("Next");
    expect(markup).toContain("disabled");
  });
});

const FACTOR_RESULT = {
  factor: {
    horizons: Object.fromEntries(([1, 5, 20] as const).map((horizon) => [String(horizon), {
      horizon,
      summary: {
        ic: { mean: 0.015, sample_deviation: 0.2, icir: 0.132, positive_fraction: 0.6, valid_session_count: 8 },
        rank_ic: { mean: 0.035, sample_deviation: 0.1, icir: 0.283, positive_fraction: 0.7, valid_session_count: 9 },
        quantile_returns: { q1: -0.1, q2: -0.05, q3: 0, q4: 0.05, q5: 0.1 },
        top_bottom_return: 0.2,
      },
      coverage: {
        signal_session_count: 10,
        ic_valid_session_count: 8,
        rank_ic_valid_session_count: 9,
        quantile_valid_session_count: 7,
      },
    }])) as Record<"1" | "5" | "20", {
      horizon: 1 | 5 | 20;
      summary: {
        ic: { mean: number; sample_deviation: number; icir: number; positive_fraction: number; valid_session_count: number };
        rank_ic: { mean: number; sample_deviation: number; icir: number; positive_fraction: number; valid_session_count: number };
        quantile_returns: Record<"q1" | "q2" | "q3" | "q4" | "q5", number>;
        top_bottom_return: number;
      };
      coverage: {
        signal_session_count: number;
        ic_valid_session_count: number;
        rank_ic_valid_session_count: number;
        quantile_valid_session_count: number;
      };
    }>,
  },
  provenance: {
    schema_version: "research-result-v2",
    research_run_id: "run_factor",
    immutable_input_sha256: "a".repeat(64),
    calculation_contracts: {},
    semantic_versions: {},
    research_kind: "factor_evaluation" as const,
  },
};

describe("ResearchResultView", () => {
  it("renders exactly the three Factor horizons and their four metrics plus coverage", () => {
    const markup = renderToStaticMarkup(<ResearchResultView result={FACTOR_RESULT} />);

    for (const horizon of [1, 5, 20]) {
      expect(markup).toContain(`aria-label="${horizon}-session Factor"`);
    }
    expect(markup.match(/<span>Rank IC<\/span>/g)).toHaveLength(3);
    expect(markup.match(/<span>Rank ICIR<\/span>/g)).toHaveLength(3);
    expect(markup.match(/<span>IC<\/span>/g)).toHaveLength(3);
    expect(markup.match(/<span>ICIR<\/span>/g)).toHaveLength(3);
    expect(markup.match(/Rank IC coverage 9\//g)).toHaveLength(3);
    expect(markup.match(/IC coverage 8\//g)).toHaveLength(3);
    expect(markup).not.toMatch(/Quantile|Top-Bottom|Positive fraction|Sample deviation/i);
    expect(markup).not.toContain("Strategy Summary");
    expect(markup).not.toContain("Daily Observations");
    expect(markup).not.toContain("Final Portfolio");
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
          formula_summary: "close",
          research_kind: "strategy_backtest",
        }}
      />,
    );
    expect(markup).toContain("Research name");
    expect(markup).toContain("Name and folder");
    expect(markup).toContain("Folder");
    expect(markup).toContain("Signals");
    expect(markup).toContain("Save changes");
    expect(markup).not.toMatch(/Draft|Rerun|Revision/);
  });
});

describe("UseAsDraftPanel", () => {
  it("classifies terminal Research states for result-page ordering", () => {
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
          formula: "close",
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
        researcherId="00000000-0000-4000-8000-000000000001"
        sourceFolderId="folder_default"
        storage={{ getItem: () => null, setItem: () => undefined }}
      />,
    );
    expect(markup).toContain("Create a draft");
    expect(markup).toContain("Create draft");
    expect(markup).toContain("Target Folder");
    expect(markup).not.toMatch(/Rerun|Run now/);
  });
});
