# 39 — Remove the old Web and authentication surface

**What to build:** Delete the now-inactive monolithic Web, old routes, and
Hosted authentication wrapper after the replacement Shell is accepted.

**Blocked by:** 01, 38.

**Status:** ready-for-agent

- [ ] The Hosted archive ref is reverified before any old surface is deleted.
- [ ] Old routes, monolithic navigation, authentication wrapper, Workspace
  Dashboard, Operations Ledger, raw JSON popup, and download surface are gone.
- [ ] Draft, frozen version, Result, Attempt, Generation, Advance, Checkpoint,
  Local/Hosted label, and deployment controls have no active page or URL.
- [ ] No feature flag, fallback route, or alternate bundle can restore the old
  product surface.
- [ ] The seven stable URLs and complete Core browser flow behave identically
  after deletion.
- [ ] Backend Hosted and legacy removal remain outside this ticket.

**How to verify:**

- Run `bun run --cwd web typecheck`, `bun run --cwd web build`, and
  `bun run --cwd web test:e2e` after deleting the old surface.
- Run `uv run pytest -q tests/architecture tests/acceptance` and confirm no
  removed product resource or authentication contract appears in HTTP output.

## Comments
