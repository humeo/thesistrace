# Keep Research Agent execution stateless and resource-addressed

Remote MCP requests never own Research execution state: effectful Tools require a caller-stable request identity and return durable ResearchRun, Research Batch, or DailyTrack identities for bounded polling. Transport sessions, protocol request IDs, notifications, and optional resources are never idempotency or recovery truth, accepting explicit polling and pagination so reconnects cannot lose or duplicate Product State work.
