---
status: accepted
---

# Make reproducible Alpha research the V1 product loop

ThesisTrace V1 turns an investment hypothesis into a reproducible research
result by freezing its data, universe, time, and execution assumptions, then
producing separate factor-evaluation and strategy-backtest conclusions with
complete provenance. ADR-0102 carries the same frozen Alpha semantics into
Daily Tracking through ADR-0148's bounded, rebuildable Working Cache rather
than a durable Alpha Matrix, and makes equivalence between reference results and
session-by-session incremental execution over the same ordered Dataset Release
sequence the end-to-end V1 correctness goal. AI Chat, MCP, notifications, and
automated trading remain outside this research loop.

ADR-0096 defines the original V1 deployment boundary as one single-node Web
Workspace for one operator, with deployment-level access control and no User,
Organization, Tenant, membership, sharing, or RBAC domain models. ADR-0110
supersedes that deployment boundary only for the hosted product: Hosted
Platform V2 gives each authenticated User exactly one private Personal
Workspace and wraps the same V1 research semantics with ownership, quotas,
scheduling, and platform operations. It does not add Organizations, shared
Workspaces, AI Chat, MCP, notifications, or automated trading to the research
loop.
