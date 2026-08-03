# 03 — Open the canonical Core runtime with empty Data

**What to build:** Start one deployment-neutral Core against real PostgreSQL and
pinned RustFS, expose the empty Data projection through the real HTTP adapter,
and establish the thin Web Shell composition seam that later resource pages
extend.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

**Implementation:** complete

- [x] One runtime assembly starts without a Local/Hosted branch, authentication,
  SQLite Product State, Temporal, or a custom object-store service.
- [x] The private PostgreSQL support owns only pool, transaction, and migration
  mechanics; Data owns its empty schema and SQL.
- [x] An empty database projects Data as `idle`, with no latest Release and an
  empty Release history.
- [x] The HTTP adapter returns the typed empty Data overview and Release history
  without branching on deployment type or exposing database fields.
- [x] The Web Shell owns only route composition and the four-resource navigation
  contract; it implements no Data, Definition, ResearchRun, or DailyTrack page
  behavior in this ticket.
- [x] This ticket establishes one reusable isolated PostgreSQL/RustFS test
  runtime that later Python and Web verification can start or address without
  undocumented manual preparation.
- [x] Restarting HTTP and worker processes preserves the valid empty state.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written. The wrapper creates clean, dedicated PostgreSQL/RustFS state, supplies
the canonical runtime environment to Python, and removes only that isolated
state when the gate exits.

```sh
set -eu
cleanup() { ./scripts/core-test-runtime down; }
trap cleanup EXIT

./scripts/core-test-runtime reset
./scripts/core-test-runtime run \
  uv run pytest -q tests/architecture tests/integration tests/acceptance
bun run --cwd web typecheck
```

The acceptance suite starts and stops two independent worker processes and two
independent HTTP processes. Both HTTP starts must return exactly the typed
`idle` Data overview with no latest Release and the empty Release history.

## Comments

- TDD red: against healthy PostgreSQL 16.10 and RustFS 1.0.0-beta.12, both
  empty-runtime integration cases failed at the product boundary with
  `NotImplementedError: canonical Core runtime is not implemented`.
- TDD green (focused): the real-service integration cases passed `2 passed`;
  the HTTP/worker process-restart acceptance passed `1 passed`; architecture
  assertions passed `5 passed`; Web typecheck passed.
- The first RustFS start exposed Docker Desktop's exhausted internal storage.
  The reusable runtime deliberately does not prune user Docker resources; its
  database and object data bind only to
  `/private/tmp/thesistrace-core-test-data`, and `reset/down` validate and clean
  only that exact test-owned root.
- `_postgres` uses `psycopg_pool.ConnectionPool` and a generic checksummed
  migration runner. Data supplies the `data` schema plan and owns every
  `data.state`/`data.releases` statement. The runtime uses the standard Boto3 S3
  client directly against RustFS; it adds no object-store server or proxy.
- Final in-ticket Python command passed `81 passed` in `175.21s` from clean
  PostgreSQL schemas and RustFS data. Web typecheck passed. Cleanup stopped both
  containers and left no file below the dedicated test-data root.
