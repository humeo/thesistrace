# Keep Research Agent execution stateless and resource-addressed

Remote MCP requests never own Research execution state: effectful tools require
a caller-stable `request_id` and return durable ResearchRun, Research Batch, or
DailyTrack identities, which Research Agents observe through bounded polling
with retry guidance. Read tools return compact summaries plus cursor-paginated
result sections, while optional MCP resources cannot be required to complete a
task, so transport sessions, notifications, unbounded results, and JSON-RPC
request IDs are not recovery or idempotency truths.
