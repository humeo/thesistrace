# Run the built-in Research Agent in a separate Host

ThesisTrace runs its built-in Research Agent in one same-origin private Agent
Host that combines CopilotKit Runtime, AG-UI/A2UI, and one Mastra Agent, discovers
its Tool inventory only from Core's scope-filtered `/mcp` endpoint, and owns no
Research resource or execution state. This deliberately adds one runtime beside
module-first Core instead of embedding model orchestration in FastAPI or the
Browser, because streaming Chat, configured model access, conversation
persistence, and the MCP OAuth client lifecycle must evolve without moving
deterministic Research behavior out of Core; the Host receives its own
PostgreSQL schema and role and no Core, Auth, RustFS, or Canonical Data authority.
Mastra owns Agent instructions, Tool choice, Memory, Threads, and Run behavior;
ThesisTrace does not add a second Folder-selection, ResearchRun-polling, Prompt,
or Agent-run state machine around it. Stopping or losing one Agent Run affects
only that Mastra/CopilotKit interaction; every ResearchRun, Research Batch, or
DailyTrack already accepted through MCP continues under Core's lifecycle.
