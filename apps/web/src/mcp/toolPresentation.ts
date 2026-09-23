// Presentation metadata only. The authenticated MCP discovery response owns
// which tools appear; this table neither exposes tools nor grants permissions.
export const toolPresentation: Record<string, { effect: "Read" | "Create" | "Update"; scope: string }> = {
  get_research_context: { effect: "Read", scope: "research:read" },
  get_alpha_catalog: { effect: "Read", scope: "research:read" },
  diagnose_alpha_formula: { effect: "Read", scope: "research:read" },
  list_research_runs: { effect: "Read", scope: "research:read" },
  get_research_run: { effect: "Read", scope: "research:read" },
  get_research_run_result: { effect: "Read", scope: "research:read" },
  submit_research_run: { effect: "Create", scope: "research:execute" },
  list_research_batches: { effect: "Read", scope: "research:read" },
  get_research_batch: { effect: "Read", scope: "research:read" },
  submit_research_batch: { effect: "Create", scope: "research:execute" },
  list_daily_tracks: { effect: "Read", scope: "tracking:read" },
  get_daily_track: { effect: "Read", scope: "tracking:read" },
  get_daily_track_result: { effect: "Read", scope: "tracking:read" },
  start_daily_track: { effect: "Create", scope: "tracking:execute" },
  refresh_daily_track: { effect: "Update", scope: "tracking:execute" },
  retry_daily_track: { effect: "Update", scope: "tracking:execute" },
};
