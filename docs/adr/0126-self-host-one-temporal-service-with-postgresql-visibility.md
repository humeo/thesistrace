---
status: superseded by ADR-0151
---

# Self-host one Temporal Service with PostgreSQL Visibility

The first Hosted Platform V2 deployment self-hosts one non-HA Temporal Service on the Compose node, using dedicated PostgreSQL persistence and Visibility databases, private endpoints, and version-pinned schema migration rather than a development or auto-setup server. This minimizes launch infrastructure while isolating Temporal state and acknowledging that durable process recovery does not provide host availability.
