# 48 — Prove post-contraction architecture invariants

**What to build:** Demonstrate that the contracted source tree implements the
accepted module boundaries, ownership rules, and one canonical runtime without
reimplementing product behavior in this ticket.

**Blocked by:** 47.

**Status:** ready-for-agent

- [ ] Data, Definitions, ResearchRuns, DailyTracks, and Publication each own
  their schema, migrations, SQL, lifecycle records, and action receipts.
- [ ] No product rule uses cross-schema SQL; cross-module admission uses only a
  private interface and the concrete caller-owned transaction.
- [ ] Dependency direction matches the accepted architecture, and Kernel,
  Data, and Publication never import their callers.
- [ ] Core imports no Hosted, old lifecycle facade, HTTP entrypoint, Web,
  Temporal, outbox, event bus, global job table, generic repository, or command
  envelope.
- [ ] A standard S3 client is the only immutable-object implementation, and
  physical object keys never enter product API or Web output.
- [ ] Stable routes expose exactly Data, Definitions, ResearchRuns, and
  DailyTracks; internal Snapshot, Result, Attempt, Advance, Checkpoint, Cache,
  and manifest concepts have no product URL.
- [ ] The HTTP action inventory is closed: ResearchRuns have no generic
  create/update/delete, DailyTracks have no generic create/delete, and no Data
  Release, Definition, ResearchRun, or DailyTrack exposes a generic Delete.
- [ ] Default verification excludes Hosted, login, deployment, SQLite fallback,
  and live Tushare while leaving the live gate separate.

**How to verify:**

- Run `uv run pytest -q tests/architecture` and review every import, schema
  ownership, route inventory, entrypoint, and forbidden-dependency assertion.
- Run the integration and Web acceptance suites once after the invariant checks
  to prove the assertions did not replace product behavior evidence.

## Comments
