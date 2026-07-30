---
status: accepted
---

# Serve the production Web build directly from Caddy

Hosted Platform V2 runs Vite only during the Web image build. The build executes
the repository's TypeScript check and Vite production build, then copies the
resulting `web/dist` assets into the versioned Caddy deployment image. The
production Compose stack runs neither the Vite development server nor a
long-lived Node Web container.

Caddy serves the static application at the public root, applies SPA fallback
for client-side routes, gives content-hashed assets long immutable caching, and
keeps the HTML entry point revalidatable so a new release becomes visible
without stale shell state. The same Caddy process reverse-proxies the
ThesisTrace API and required InsForge Auth and Storage routes under ADR-0143.

The Web assets, Caddy configuration, and compatible API release are deployed as
one pinned Hosted Platform V2 release. Local development may continue to use
the Vite server and its development proxy; that path is not part of the
production runtime or resource budget.
