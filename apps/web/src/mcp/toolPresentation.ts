// Presentation metadata only. The authenticated MCP discovery response owns
// which tools appear; this table neither exposes tools nor grants permissions.
export const toolPresentation: Record<string, { title: string; description: string; effect: "Read" | "Create" | "Update"; scope: string }> = {
  get_research_context: { title: "Check research readiness", description: "Read dataset readiness and available research folders.", effect: "Read", scope: "research:read" },
  get_alpha_catalog: { title: "Explore formula building blocks", description: "Explore fields and operators for writing formulas.", effect: "Read", scope: "research:read" },
  diagnose_alpha_formula: { title: "Check an alpha formula", description: "Check a formula before submitting research.", effect: "Read", scope: "research:read" },
  list_research_runs: { title: "Browse research runs", description: "Browse your research runs.", effect: "Read", scope: "research:read" },
  get_research_run: { title: "Check run progress", description: "Check progress and the current run state.", effect: "Read", scope: "research:read" },
  get_research_run_result: { title: "Read research results", description: "Read a selected section of a research result.", effect: "Read", scope: "research:read" },
  submit_research_run: { title: "Start a research run", description: "Submit a new research run.", effect: "Create", scope: "research:execute" },
  list_research_batches: { title: "Browse research batches", description: "Browse your research batches.", effect: "Read", scope: "research:read" },
  get_research_batch: { title: "Check batch progress", description: "Check a batch and its individual runs.", effect: "Read", scope: "research:read" },
  submit_research_batch: { title: "Start a research batch", description: "Submit multiple research items as a batch.", effect: "Create", scope: "research:execute" },
  list_daily_tracks: { title: "Browse daily tracks", description: "Browse your daily tracks.", effect: "Read", scope: "tracking:read" },
  get_daily_track: { title: "Check a daily track", description: "Check the state and progress of a daily track.", effect: "Read", scope: "tracking:read" },
  get_daily_track_result: { title: "Read daily observations", description: "Read daily observations and track results.", effect: "Read", scope: "tracking:read" },
  start_daily_track: { title: "Start a daily track", description: "Start tracking from a completed research run.", effect: "Create", scope: "tracking:execute" },
  refresh_daily_track: { title: "Refresh a daily track", description: "Request a refresh of a daily track.", effect: "Update", scope: "tracking:execute" },
  retry_daily_track: { title: "Retry a daily track", description: "Retry a daily track that needs attention.", effect: "Update", scope: "tracking:execute" },
};
