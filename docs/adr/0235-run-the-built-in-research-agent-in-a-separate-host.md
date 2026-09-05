# Run the built-in Research Agent in a separate Host

A private Agent Host owns model orchestration and durable Chat interaction while Core alone owns accepted Research execution and results. Mastra and CopilotKit supply the model and streaming integration, while ThesisTrace persists Turn controls, command receipts, and conversation projections; this separates conversation recovery from deterministic research recovery at the cost of an additional service. The Host obtains Research capabilities from Core MCP and has no direct access to Core, Auth, or Canonical data stores.
