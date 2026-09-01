import type { RecordedToolCall } from "./scripted-trajectory.js";

export const TRACK_ID = "track_0123456789abcdef0123";
export const ORIGIN_RUN_ID = "run_0123456789abcdef0123";
export const DAILY_TRACK_TOOL_NAMES = [
  "get_research_run", "list_daily_tracks", "start_daily_track",
  "get_daily_track", "get_daily_track_result", "retry_daily_track",
] as const;

export function dailyTrackDetail(status = "active", phase = "up_to_date", session = "2024-01-31"): Record<string, unknown> {
  return {
    id: TRACK_ID, status,
    origin: { research_run_id: ORIGIN_RUN_ID, origin_session: "2024-01-30", result_checksum_sha256: "a".repeat(64) },
    progress: { head_session: session, data_through_session: session, phase, lag_sessions: 0 },
    blocked_reason: status === "blocked" ? "Financial Coverage ends before the next Research Session." : null,
    action_eligibility: { retry: status === "blocked", stop: ["active", "blocked"].includes(status) },
    available_result_sections: ["factor", "strategy_summary", "strategy_observations", "origin", "provenance"],
    retry_after_seconds: status === "blocked" || status === "stopped" ? null : phase === "up_to_date" ? 30 : 2,
    private_checkpoint: "private-daily-track-provenance",
  };
}

export function dailyTrackFixtureOutput(call: RecordedToolCall, session = "2024-01-31"): Record<string, unknown> {
  switch (call.name) {
    case "get_research_run": return {
      id: call.input.run_id, status: "succeeded",
      input: { research_kind: "strategy_backtest", formula: "rank(close)" },
      available_result_sections: ["strategy_summary", "strategy_observations", "provenance"],
    };
    case "list_daily_tracks": return { items: [], next_cursor: null };
    case "start_daily_track":
    case "retry_daily_track": return { outcome: "accepted", track_id: TRACK_ID, status: "active", replayed: false, retry_after_seconds: 1 };
    case "get_daily_track": return dailyTrackDetail("active", "up_to_date", session);
    case "get_daily_track_result": return {
      track_id: call.input.track_id, section: call.input.section,
      ...(call.input.section === "strategy_summary" ? {
        strategy_session: session, origin_session: "2024-01-30",
        summary: { sharpe: 1.23, net_cumulative_return: 0.17, maximum_drawdown: { value: -0.08 } },
      } : call.input.section === "strategy_observations" ? {
        items: [{ session, net_nav: "1.17", net_cash: "4000.00", holdings_count: 10, transaction_cost_cny: "13.50" }], next_cursor: null,
      } : {
        origin_research_run_id: ORIGIN_RUN_ID, tracking_strategy_session: session,
        frozen_research_input: { formula: "rank(close)" },
      }),
      private_checkpoint: "private-daily-track-provenance",
    };
    case "render_a2ui": return { rendered: call.input.surfaceId, a2ui_operations: [] };
    default: throw new Error(`Unexpected DailyTrack fixture Tool: ${call.name}`);
  }
}
