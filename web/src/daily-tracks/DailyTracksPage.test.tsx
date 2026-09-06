import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  dailyTrackCanRefresh,
  dailyTrackNeedsPolling,
  TrackingOriginView,
  TrackingProgressView,
  type DailyTrackDetail,
} from "./DailyTracksPage";
import {
  DailyTrackAnalysisView,
  type DailyTrackAnalysis,
} from "./DailyTrackAnalysisView";
import { CurrentHoldings, ObservationSummary, RebalanceSchedule, TrackingReturnChart, type DailyTrackObservation } from "./DailyTrackObservationView";

const observation: DailyTrackObservation = {
  session: "2026-08-18", net_asset_value_cny: "1100", cash_cny: "200",
  net_change_cny: "100", net_return: 0.1, transaction_cost_cny: "2.75", session_count: 1,
  holdings: [{ instrument_id: "000001.SZ", shares: 100, market_value_cny: "900", weight: 9 / 11 }],
  rebalance_interval: 5, pending_signal_session: null, sessions_until_next_signal: 4,
  returns: [{ session: "2026-08-17", net_return: 0 }, { session: "2026-08-18", net_return: 0.1 }],
};

describe("Daily observation presentation", () => {
  it("labels the tracking period and displays the published account", () => {
    const markup = renderToStaticMarkup(<ObservationSummary observation={observation} originSession="2026-08-17" />);
    expect(markup).toContain("Return since tracking");
    expect(markup).toContain("10.00%");
    expect(markup).toContain("Since 2026-08-17");
    expect(markup).toContain("CN¥1,100.00");
    expect(markup).toContain("CN¥200.00");
    expect(markup).toContain("As of 2026-08-18");
  });

  it("renders actual shares separately from adjusted market value and cash", () => {
    const markup = renderToStaticMarkup(<CurrentHoldings observation={observation} />);
    expect(markup).toContain("000001.SZ");
    expect(markup).toContain("<td>100</td>");
    expect(markup).toContain("CN¥900.00");
    expect(markup).toContain("81.82%");
    expect(markup).toContain("18.18%");
  });

  it("keeps stale schedules distinct from available trade instructions", () => {
    const markup = renderToStaticMarkup(<RebalanceSchedule observation={observation} isBehind isStopped={false} />);
    expect(markup).toContain("Next signal in 4 trading sessions");
    expect(markup).toContain("Tracking is behind the available data");
    expect(markup).toContain("Buy and sell instructions are not available yet");
    const stopped = renderToStaticMarkup(<RebalanceSchedule observation={observation} isBehind isStopped />);
    expect(stopped).toContain("Tracking stopped");
    expect(stopped).not.toContain("Update the track");
  });

  it("does not invent a performance curve before the first completed update", () => {
    const markup = renderToStaticMarkup(<TrackingReturnChart observation={{ ...observation, returns: [{ session: "2026-08-17", net_return: 0 }] }} originSession="2026-08-17" />);
    expect(markup).toContain("Your daily observations start here");
    expect(markup).not.toContain("<canvas");
  });
});

describe("DailyTrack detail polling", () => {
  const progress = (phase: DailyTrackDetail["progress"]["phase"]) => ({
    phase,
  }) as DailyTrackDetail["progress"];

  it("polls only while an explicit action is unresolved", () => {
    expect(dailyTrackNeedsPolling({ status: "stopping", progress: progress("stopping") })).toBe(true);
    expect(dailyTrackNeedsPolling({ status: "active", progress: progress("queued") })).toBe(true);
    expect(dailyTrackNeedsPolling({ status: "active", progress: progress("calculating") })).toBe(true);
    expect(dailyTrackNeedsPolling({ status: "active", progress: progress("waiting") })).toBe(false);
    expect(dailyTrackNeedsPolling({ status: "stopped", progress: progress("stopped") })).toBe(false);
  });

  it("offers Refresh only for an active, lagging, idle track", () => {
    expect(dailyTrackCanRefresh({ status: "active", lag_sessions: 2, progress: progress("waiting") })).toBe(true);
    expect(dailyTrackCanRefresh({ status: "active", lag_sessions: 0, progress: progress("up_to_date") })).toBe(false);
    expect(dailyTrackCanRefresh({ status: "active", lag_sessions: 2, progress: progress("queued") })).toBe(false);
    expect(dailyTrackCanRefresh({ status: "blocked", lag_sessions: 2, progress: progress("blocked") })).toBe(false);
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
    expect(markup).toContain("CSI 300");
    expect(markup).not.toContain("沪深300");
    expect(markup).not.toContain("Fixed Strategy Benchmark");
    expect(markup).not.toContain("数据截至");
    expect(markup).not.toContain("d".repeat(64));
    expect(markup).toContain("504 Research Sessions");
    expect(markup).not.toContain("Net Excess");
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
    expect(unavailableMarkup).toContain("CSI 300 comparison unavailable");
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
