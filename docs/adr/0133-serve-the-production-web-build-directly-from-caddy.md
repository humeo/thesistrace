---
status: superseded by ADR-0151
---

# Serve the production Web build directly from Caddy

Hosted Platform V2 runs Vite only while building the versioned Web image and serves the resulting static application directly from Caddy in production. This removes development servers and a long-lived Node Web container from the runtime while keeping the Web assets, Caddy configuration, and compatible API in one pinned release.
