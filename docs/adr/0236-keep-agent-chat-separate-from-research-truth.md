# Keep Agent Chat separate from Research truth

Agent Chat and Core Research have independent lifecycles. An Agent Chat Session
and its Alpha Proposals are durable Researcher-owned interaction state that may
produce multiple ResearchRuns, while accepted Research remains authoritative
through its frozen inputs, Data Generation, bounded Agent provenance, lifecycle,
and Result Bundle. Deleting an Agent Chat Session removes only that Chat's
Thread, Messages, and A2UI state; it neither discovers nor mutates any
ResearchRun, Research Batch, DailyTrack, or Result Bundle the conversation may
reference. Mastra Memory supplies only the current Agent Chat Session as
conversational context; the Research Agent may inspect authorized Core Research
through MCP but never searches or recalls another Chat transcript.
