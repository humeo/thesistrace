# Expose Research Agent access through a native Core MCP adapter

ThesisTrace exposes Research Agent capabilities through a Python MCP adapter at
the same seam as its HTTP and Worker adapters, calling the existing module
interfaces instead of mirroring HTTP routes or moving domain behavior into an
edge Worker. One MCP deployment serves one controlled ThesisTrace installation,
uses portable standard MCP tools for ResearchRun, Research Batch, DailyTrack,
and read-only Research Folder context, and never grants Data Operator authority;
an edge Worker may authenticate, rate-limit, and forward requests without
becoming a second domain implementation.
