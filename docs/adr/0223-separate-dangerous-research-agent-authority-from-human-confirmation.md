# Separate dangerous Research Agent authority from human confirmation

Remote MCP registers ResearchRun and Research Batch cancellation and DailyTrack
Stop only for OAuth grants carrying dedicated dangerous-action scopes that
default grants omit. The server enforces those scopes, resource state,
idempotency, and audit; `destructiveHint` and a trusted Agent Host provide human
confirmation but are not authorization, and the server does not issue a token
that falsely claims to prove a person approved the action.
