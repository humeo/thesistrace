# Keep Agent content out of operational telemetry

Agent messages, A2UI payloads, model requests and responses, MCP Tool arguments
and results, Alpha Formulae, Investment Hypotheses, credentials, and access
tokens are excluded from Agent Host logs and traces; owner-scoped Agent Chat or
Core Product State remains the only durable home for that content. Agent Host
telemetry uses a closed metadata allowlist for correlation identities, selected
model and reasoning effort, token usage, step count, duration, status, and
sanitized error category, preserving cost and reliability evidence without
turning Mastra or CopilotKit observability into a second content store.
