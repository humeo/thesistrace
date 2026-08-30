# Expose Research Agent access through a native Core MCP adapter

ThesisTrace exposes ResearchRun, Research Batch, DailyTrack, and read-only Research Folder capabilities through one native Core MCP adapter that calls the existing module interfaces and never grants Data Operator authority. Streamable HTTP runs in the Core API process and local stdio uses the same capability registry; both expose bounded product-semantic results rather than mirroring HTTP routes, physical Result storage, private recovery state, or a second domain implementation.
