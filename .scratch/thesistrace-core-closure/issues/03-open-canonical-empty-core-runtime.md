# 03 — Open the canonical Core runtime with empty Data

**What to build:** Start one deployment-neutral Core against real PostgreSQL and
pinned RustFS, expose the empty Data projection through the real HTTP adapter,
and establish the thin Web Shell composition seam that later resource pages
extend.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] One runtime assembly starts without a Local/Hosted branch, authentication,
  SQLite Product State, Temporal, or a custom object-store service.
- [ ] The private PostgreSQL support owns only pool, transaction, and migration
  mechanics; Data owns its empty schema and SQL.
- [ ] An empty database projects Data as `idle`, with no latest Release and an
  empty Release history.
- [ ] The HTTP adapter returns the typed empty Data overview and Release history
  without branching on deployment type or exposing database fields.
- [ ] The Web Shell owns only route composition and the four-resource navigation
  contract; it implements no Data, Definition, ResearchRun, or DailyTrack page
  behavior in this ticket.
- [ ] This ticket establishes one reusable isolated PostgreSQL/RustFS test
  runtime that later Python and Web verification can start or address without
  undocumented manual preparation.
- [ ] Restarting HTTP and worker processes preserves the valid empty state.

**How to verify:**

- Run `uv run pytest -q tests/architecture tests/integration tests/acceptance`
  against isolated PostgreSQL and pinned RustFS.
- Run `bun run --cwd web typecheck`, then start the documented isolated runtime
  twice and request the Data overview through HTTP; both starts must return the
  same valid empty projection.

## Comments
