import type { RecordedToolCall } from "./scripted-trajectory.js";

export const BATCH_ID = "batch_0123456789abcdef0123";
export const CHILD_IDS = ["run_0123456789abcdef0123", "run_abcdef0123456789abcd"] as const;
export const BATCH_TOOL_NAMES = [
  "get_research_context", "get_alpha_catalog", "diagnose_alpha_formula",
  "submit_research_batch", "list_research_batches", "get_research_batch",
  "get_research_run", "get_research_run_result",
] as const;

export type BatchFixtureMode = "factor_evaluation" | "strategy_sweep";

export function batchFixtureOutput(
  mode: BatchFixtureMode,
  call: RecordedToolCall,
): Record<string, unknown> {
  switch (call.name) {
    case "get_research_context": return {
      authoring_constraints: {
        holdings_count: { maximum: 100, minimum: 1 },
        neutralizations: ["none", "industry"],
        rebalance_every_sessions: { maximum: 20, minimum: 1 },
        universes: ["top300", "top1000"],
      },
      data_overview: { market_coverage: { end: "2024-01-31", start: "2024-01-02" } },
      // Batch commands have no folder_id. Deliberately omit single-run folders.
      private_provenance: "private-batch-core-provenance",
    };
    case "get_alpha_catalog": return { unknown_identifiers: [], fields: [{ identifier: "close" }], builtins: [{ identifier: "rank" }] };
    case "diagnose_alpha_formula": return { diagnostics: [], valid: true };
    case "submit_research_batch": return { outcome: "accepted", batch_id: BATCH_ID, status: "queued", replayed: false };
    case "list_research_batches": return { items: [{ id: BATCH_ID, batch_kind: mode, status: "succeeded" }], next_cursor: null };
    case "get_research_batch": return batchDetail(mode);
    case "get_research_run": return {
      id: call.input.run_id,
      status: "succeeded",
      input: {
        formula: mode === "factor_evaluation" && call.input.run_id === CHILD_IDS[1] ? "-rank(close)" : "rank(close)",
        research_kind: mode === "factor_evaluation" ? "factor_evaluation" : "strategy_backtest",
      },
      available_result_sections: mode === "factor_evaluation" ? ["factor", "provenance"] : ["strategy_summary", "strategy_observations", "provenance"],
    };
    case "get_research_run_result": return call.input.section === "strategy_observations"
      ? { run_id: call.input.run_id, section: "strategy_observations", items: [{ session: "2024-01-03" }], next_cursor: null }
      : {
          run_id: call.input.run_id,
          section: call.input.section,
          research_kind: mode === "factor_evaluation" ? "factor_evaluation" : "strategy_backtest",
          ...(mode === "factor_evaluation" ? {
            factor: { horizons: { "5": { summary: {
              rank_ic: { mean: call.input.run_id === CHILD_IDS[0] ? 0.12 : -0.12 },
              top_bottom_return: call.input.run_id === CHILD_IDS[0] ? 0.034 : -0.034,
            } } } },
          } : {
            metrics: { sharpe: 1.23, net_cumulative_return: 0.17, maximum_drawdown: { value: -0.08 } },
          }),
          private_provenance: "private-batch-core-provenance",
        };
    case "render_a2ui": return { rendered: call.input.surfaceId, a2ui_operations: [] };
    default: throw new Error(`Unexpected Batch fixture Tool: ${call.name}`);
  }
}

export function batchDetail(mode: BatchFixtureMode, status = "succeeded"): Record<string, unknown> {
  const keys = mode === "factor_evaluation" ? ["positive-price-rank", "negative-price-rank"] : ["focused-holdings", "broad-holdings"];
  const completed = ["succeeded", "completed_with_failures", "failed"].includes(status) ? 2 : 0;
  return {
    id: BATCH_ID, batch_kind: mode, status,
    scope: { start_date: "2024-01-02", end_date: "2024-01-31", universe: "top1000", neutralization: "none" },
    progress: mode === "factor_evaluation"
      ? { completed_factor_tasks: completed, total_factor_tasks: 2 }
      : { completed_strategy_tasks: completed, total_strategy_tasks: 2, shared_alpha_factor_status: completed === 2 ? "succeeded" : "running" },
    retry_after_seconds: ["running", "queued"].includes(status) ? 2 : null,
    items: CHILD_IDS.map((id, ordinal) => ({
      ordinal: ordinal + 1, item_key: keys[ordinal], research_run_id: id,
      run_availability: "available", status: status === "completed_with_failures" && ordinal === 1 ? "failed" : status === "completed_with_failures" ? "succeeded" : status,
    })),
  };
}
