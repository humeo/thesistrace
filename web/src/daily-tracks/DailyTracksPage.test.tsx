import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { TrackingOriginView, type DailyTrackDetail } from "./DailyTracksPage";

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
