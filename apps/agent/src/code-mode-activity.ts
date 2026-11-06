import type { AgentFailureCode } from "@thesistrace/contracts/agent-failure";

export const CODE_MODE_TOOL_NAME = "execute_typescript";
export const CODE_MODE_ACTIVITY = "research_code_mode_activity";
export const CODE_MODE_READ_TOOLS = Object.freeze([
  "get_research_context", "get_authoring_reference", "get_alpha_catalog",
  "diagnose_alpha_formula", "diagnose_research_spec", "list_research_runs",
  "get_research_run", "get_research_run_result", "list_research_batches", "get_research_batch",
  "list_daily_tracks", "get_daily_track", "get_daily_track_result",
] as const);

export type CodeModeActivity = Readonly<{
  toolCallId: string;
  name: string;
  status: "running" | "complete" | "failed";
  failureCode?: AgentFailureCode;
  resultBytes?: number;
}>;

/** Host activity metadata, never model tool arguments or results. */
export function readCodeModeActivity(value: unknown): CodeModeActivity | undefined {
  if (!value || typeof value !== "object") return undefined;
  const activity = value as Record<string, unknown>;
  if (Object.keys(activity).some(key => !["toolCallId", "name", "status", "failureCode", "resultBytes"].includes(key))
    || typeof activity.toolCallId !== "string" || activity.toolCallId.length > 256
    || !/^[A-Za-z0-9_.:-]+:external:[1-9][0-9]?$/.test(activity.toolCallId)
    || typeof activity.name !== "string" || !(CODE_MODE_READ_TOOLS as readonly string[]).includes(activity.name)
    || !["running", "complete", "failed"].includes(activity.status as string)
    || activity.failureCode !== undefined && !["AGENT_LIMIT", "AGENT_RUN_INTERRUPTED", "MCP_TRANSIENT", "MCP_AUTHENTICATION", "TOOL_ERROR", "TOOL_REJECTION"].includes(activity.failureCode as string)
    || activity.resultBytes !== undefined && (!Number.isSafeInteger(activity.resultBytes) || (activity.resultBytes as number) < 0)) return undefined;
  return activity as CodeModeActivity;
}
