---
status: superseded by ADR-0143
scope: archived - outside the active Core
---

# Expose only Caddy at the public network edge

Hosted Platform V2 exposes only Caddy at the public network edge to terminate TLS and serve one browser Origin, while application, data, orchestration, worker, and operator services remain private. This minimized the initial attack and cross-origin surfaces but is superseded by ADR-0143.
