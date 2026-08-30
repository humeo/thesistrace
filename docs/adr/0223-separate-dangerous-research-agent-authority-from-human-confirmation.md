# Separate dangerous Research Agent authority from human confirmation

Remote MCP exposes ResearchRun and Research Batch cancellation and DailyTrack Stop only through dedicated dangerous-action scopes omitted from default grants. The server enforces authority, resource state, and idempotency, while Host confirmation and destructive annotations remain user-experience signals rather than authorization proof.
