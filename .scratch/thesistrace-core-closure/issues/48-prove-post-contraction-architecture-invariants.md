# 48 — Prove post-contraction architecture invariants

**What to build:** Demonstrate that the contracted source tree implements the
accepted module boundaries, ownership rules, and one canonical runtime without
reimplementing product behavior in this ticket.

**Blocked by:** 47.

**Status:** complete

- [x] Data, Definitions, ResearchRuns, DailyTracks, and Publication each own
  their schema, migrations, SQL, lifecycle records, and action receipts.
- [x] No product rule uses cross-schema SQL; cross-module admission uses only a
  private interface and the concrete caller-owned transaction.
- [x] Dependency direction matches the accepted architecture, and Kernel,
  Data, and Publication never import their callers.
- [x] Core imports no Hosted, old lifecycle facade, HTTP entrypoint, Web,
  Temporal, outbox, event bus, global job table, generic repository, or command
  envelope.
- [x] A standard S3 client is the only immutable-object implementation, and
  physical object keys never enter product API or Web output.
- [x] Stable routes expose exactly Data, Definitions, ResearchRuns, and
  DailyTracks; internal Snapshot, Result, Attempt, Advance, Checkpoint, Cache,
  and manifest concepts have no product URL.
- [x] The HTTP action inventory is closed: ResearchRuns have no generic
  create/update/delete, DailyTracks have no generic create/delete, and no Data
  Release, Definition, ResearchRun, or DailyTrack exposes a generic Delete.
- [x] Default verification excludes Hosted, login, deployment, SQLite fallback,
  and live Tushare while leaving the live gate separate.

**How to verify:**

```sh
set -eu

uv run pytest -q tests/architecture

trap './scripts/core-test-runtime down' EXIT
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q tests/integration tests/acceptance
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:e2e
```

## Comments

- Implementation: `4bf0b47`; architecture review corrections: `87a2022`;
  bounded acceptance synchronization correction: `f07a215`.
- The architecture proof normalizes absolute and relative imports, proves the
  allowed dependency graph is closed and acyclic, scans product modules for
  foreign-schema SQL, freezes lifecycle table ownership, inventories the exact
  20 HTTP routes from the assembled FastAPI app, and verifies the default Make
  gate independently from live Tushare.
- Independent review round 1 found import, SQL-literal, and route-registration
  bypasses. Round 2 returned Standards PASS / Spec PASS after the proof was
  made structural. Round 3 returned PASS / PASS after one pre-barrier test wait
  was widened from 10 to 60 seconds without changing Stop, fence, publication,
  or product timeouts.
- Two earlier full behavior attempts exposed independent runtime-test issues:
  one fixed synchronization budget and repeated RustFS incomplete response
  streams. The latter was moved to blocking Bug Ticket 50, independently
  reviewed, fixed, and closed rather than absorbed into this architecture
  ticket.
- Final stronger clean verification through `make check`: Architecture remained
  green within Kernel/Architecture/Adapter `141 passed`; Web typecheck/build
  passed; isolated Integration/Acceptance `101 passed` in `725.73s`; clean-reset
  Web E2E `18 passed` in `1.3m`.
