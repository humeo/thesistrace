---
status: accepted
---

# Make reproducible Alpha research the V1 product loop

ThesisTrace V1 turns an investment hypothesis into a reproducible research
result by freezing its data, universe, time, and execution assumptions, then
producing separate factor-evaluation and strategy-backtest conclusions with
complete provenance. ADR-0102 carries the same frozen Alpha semantics into
Daily Tracking through ADR-0148's bounded, rebuildable Working Cache rather
than a durable Alpha Matrix, and makes equivalence between batch results and
session-by-session incremental replay the end-to-end V1 correctness goal. AI
Chat, MCP, multi-tenancy, notifications, and automated trading remain outside
this first product loop.

ADR-0096 exposes this loop as one single-node Web Workspace for one operator
per deployment. V1 relies on the deployment boundary for access control and
does not create User, Organization, Tenant, membership, sharing, or RBAC
domain models.
