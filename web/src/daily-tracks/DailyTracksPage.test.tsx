import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  TrackingOriginView,
  TrackingProgressView,
  type DailyTrackDetail,
} from "./DailyTracksPage";
import { DailyTrackAnalysisView } from "./DailyTrackAnalysisView";

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
    const markup = renderToStaticMarkup(
      <DailyTrackAnalysisView analysis={{
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
              annualized_excess_return: 0.03,
              maximum_drawdown: { value: -0.02 },
              sharpe: 1.2,
              transaction_costs: { cumulative_amount: 25 },
            },
          },
          benchmark: { universe: "top300", methodology: "selected_universe_equal_weight" },
          observations: [],
        },
      }} />,
    );

    expect(markup).toContain("Factor Summary");
    expect(markup).toContain("Strategy Summary");
    expect(markup).toContain("Rank IC coverage 1/2");
    expect(markup).not.toMatch(/Predictive evidence|Fixed origin|signal sessions/i);
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
        benchmark_nav: "1.001",
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
    expect(markup).toContain("10000995");
    expect(markup).toContain("8999995");
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
        benchmark_nav: "1.001",
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
