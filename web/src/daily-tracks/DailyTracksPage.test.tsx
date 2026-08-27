import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  dailyTrackNeedsPolling,
  TrackingOriginView,
  TrackingProgressView,
  type DailyTrackDetail,
} from "./DailyTracksPage";
import {
  DailyTrackAnalysisView,
  type DailyTrackAnalysis,
} from "./DailyTrackAnalysisView";

describe("DailyTrack detail polling", () => {
  it("keeps loading while Stop is waiting for child-exit confirmation", () => {
    expect(dailyTrackNeedsPolling("stopping")).toBe(true);
    expect(dailyTrackNeedsPolling("stopped")).toBe(false);
  });
});

describe("DailyTrackAnalysisView", () => {
  it("uses the shared concise result language", () => {
    const horizon = {
      horizon: 1 as const,
      summary: {
        ic: { mean: 0.1, sample_deviation: 0, icir: 1, positive_fraction: 1, valid_session_count: 1 },
        rank_ic: { mean: 0.2, sample_deviation: 0, icir: 2, positive_fraction: 1, valid_session_count: 1 },
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
    const analysis = {
      factor: {
        horizons: {
          "1": horizon,
          "5": { ...horizon, horizon: 5 },
          "20": { ...horizon, horizon: 20 },
        },
      },
      strategy: {
        summary: {
          metrics: {
            net_cumulative_return: 0.1,
            benchmark_cumulative_return: 0.05,
            benchmark_cagr: 0.07,
            annualized_excess_return: 0.03,
            maximum_drawdown: { value: -0.02 },
            sharpe: 1.2,
            transaction_costs: { cumulative_amount: 25 },
          },
        },
        observations: [],
        comparison: {
          status: "available",
          benchmark: {
            id: "csi300-price-index-open",
            display_name: "沪深300",
            ts_code: "399300.SZ",
            kind: "price_index",
            coordinate: "open",
            snapshot_sha256: "d".repeat(64),
            coverage: {
              start_session: "2010-01-04",
              end_session: "2026-08-13",
            },
            published_at: "2026-08-13T18:00:00Z",
          },
          entry: {
            session: "2024-08-01",
            benchmark_open_level: "3500.1",
            initial_cash_cny: "10000000",
          },
          terminal: {
            session: "2026-08-05",
            benchmark_open_level: "4200.12",
            net_nav: "11000000",
          },
          metrics: {
            net_strategy_cumulative_return: 0.1,
            benchmark_cumulative_return: 0.05,
            net_strategy_cagr: 0.14,
            benchmark_cagr: 0.07,
            annualized_excess_return: 0.03,
          },
          curves: Array.from({ length: 504 }, (_, index) => ({
            session: new Date(Date.UTC(2024, 0, 1 + index)).toISOString().slice(0, 10),
            net_strategy_return: 0.25 + (index / 10_000),
            benchmark_relative_return: 0.2 + (index / 20_000),
            net_excess_nav: 1.04 + (index / 100_000),
            net_excess_return: 0.04 + (index / 100_000),
          })),
        },
      },
    } satisfies DailyTrackAnalysis;
    const markup = renderToStaticMarkup(
      <DailyTrackAnalysisView analysis={analysis} />,
    );

    expect(markup).toContain("Factor Summary");
    expect(markup).toContain("Strategy Summary");
    expect(markup).toContain("Rank IC coverage 1/2");
    expect(markup).toContain("沪深300");
    expect(markup).toContain("数据截至 <time dateTime=\"2026-08-13\">2026-08-13</time>");
    expect(markup).toContain("504 Research Sessions");
    expect(markup).toContain("Net Excess");
    expect(markup).not.toMatch(/Predictive evidence|Fixed origin|signal sessions/i);

    const unavailableMarkup = renderToStaticMarkup(
      <DailyTrackAnalysisView
        analysis={{
          ...analysis,
          strategy: {
            ...analysis.strategy,
            comparison: {
              status: "unavailable",
              reason: "benchmark_snapshot_unavailable",
            },
          },
        }}
      />,
    );
    expect(unavailableMarkup).toContain("沪深300 comparison unavailable");
    expect(unavailableMarkup).not.toContain("<figure");
  });
});

describe("TrackingProgressView", () => {
  it("shows the frozen target without claiming unpublished sessions are complete", () => {
    const markup = renderToStaticMarkup(
      <TrackingProgressView
        progress={{
          head_session: "2026-08-05",
          lag_sessions: 65,
          phase: "calculating",
          target_start_session: "2026-08-06",
          target_end_session: "2026-11-03",
          target_session_count: 63,
          completed_target_sessions: 0,
          current_session: "2026-08-06",
          cycle_attempt: 1,
          cycle_attempt_limit: 3,
          retry_wait: false,
          next_attempt_eligible_at: null,
        }}
      />,
    );

    expect(markup).toContain("Advance phase");
    expect(markup).toContain("calculating");
    expect(markup).toContain("2026-08-06 to 2026-11-03");
    expect(markup).toContain("63 sessions");
    expect(markup).not.toContain("completed");
  });

  it("shows persisted retry eligibility without showing transient completion", () => {
    const markup = renderToStaticMarkup(
      <TrackingProgressView
        progress={{
          head_session: "2026-08-05",
          lag_sessions: 3,
          phase: "retry_wait",
          target_start_session: "2026-08-06",
          target_end_session: "2026-08-10",
          target_session_count: 3,
          completed_target_sessions: 0,
          current_session: null,
          cycle_attempt: 2,
          cycle_attempt_limit: 3,
          retry_wait: true,
          next_attempt_eligible_at: "2026-08-18T00:00:30+00:00",
        }}
      />,
    );

    expect(markup).toContain("retry_wait");
    expect(markup).toContain("2/3");
    expect(markup).toContain("Retry eligible");
    expect(markup).toContain("2026-08-18T00:00:30+00:00");
    expect(markup).not.toContain("Current session");
    expect(markup).not.toContain("completed");
  });

  it("shows stopping as non-terminal child confirmation", () => {
    const markup = renderToStaticMarkup(
      <TrackingProgressView
        progress={{
          head_session: "2026-08-05",
          lag_sessions: 1,
          phase: "stopping",
          target_start_session: "2026-08-06",
          target_end_session: "2026-08-06",
          target_session_count: 1,
          completed_target_sessions: 0,
          current_session: "2026-08-06",
          cycle_attempt: 1,
          cycle_attempt_limit: 3,
          retry_wait: false,
          next_attempt_eligible_at: null,
        }}
      />,
    );

    expect(markup).toContain("stopping");
    expect(markup).toContain("Current session");
    expect(markup).not.toContain("completed");
  });
});

describe("TrackingOriginView", () => {
  it("shows the exact historical account from which tracking continues", () => {
    const origin: DailyTrackDetail["origin"] = {
      seed_run_id: "run_seed",
      seed_research_available: true,
      result_checksum_sha256: "a".repeat(64),
      strategy_session: "2026-08-05",
      terminal_account: {
        session: "2026-08-05",
        gross_cash: "9000000",
        net_cash: "8999995",
        gross_nav: "10001000",
        net_nav: "10000995",
        cumulative_transaction_cost: "5",
        positions: [],
        rebalance_phase: {
          origin_session: "2026-08-03",
          report_session_count: 3,
          rebalance_interval: 1,
          completed_intervals: 2,
        },
        pending_signal: null,
      },
    };

    const markup = renderToStaticMarkup(<TrackingOriginView origin={origin} />);

    expect(markup).toContain("Tracking Origin");
    expect(markup).toContain("2026-08-05");
    expect(markup).toContain('title="10000995"');
    expect(markup).toContain("CN¥10,000,995.00");
    expect(markup).toContain('title="8999995"');
    expect(markup).toContain("CN¥8,999,995.00");
    expect(markup).toContain("Origin holdings");
    expect(markup).not.toMatch(/Generation|manifest|checkpoint|fence|object location/i);
  });

  it("renders a deleted seed as provenance text instead of a broken link", () => {
    const origin: DailyTrackDetail["origin"] = {
      seed_run_id: "run_deleted",
      seed_research_available: false,
      result_checksum_sha256: "a".repeat(64),
      strategy_session: "2026-08-05",
      terminal_account: {
        session: "2026-08-05",
        gross_cash: "9000000",
        net_cash: "8999995",
        gross_nav: "10001000",
        net_nav: "10000995",
        cumulative_transaction_cost: "5",
        positions: [],
        rebalance_phase: {
          origin_session: "2026-08-03",
          report_session_count: 3,
          rebalance_interval: 1,
          completed_intervals: 2,
        },
        pending_signal: null,
      },
    };
    const markup = renderToStaticMarkup(<TrackingOriginView origin={origin} />);
    expect(markup).toContain("run_deleted (deleted)");
    expect(markup).not.toContain('href="/research-runs/run_deleted"');
  });
});
