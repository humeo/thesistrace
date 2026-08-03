# 10 — Publish the first Fixture Dataset Release

**What to build:** Let a user request Data Update and later see the first
immutable Fixture Dataset Release through the canonical Web, HTTP, worker,
PostgreSQL, Publication, and RustFS path.

**Blocked by:** 06.

**Status:** ready-for-agent

**Implementation:** complete

- [x] Data Update durably returns `accepted` without waiting for collection or
  publication.
- [x] A Data-owned worker claims the request and performs the first three-year
  Bootstrap from the canonical Fixture adapter.
- [x] Fixture implements only the DataSource collection and canonical mapping
  contract; it knows no Release ID, PostgreSQL, S3, ResearchRun, or DailyTrack.
- [x] Data validates coverage, schema, point-in-time, calendar, and publication
  rules before creating an immutable Dataset Release.
- [x] Data supplies canonical contract, collection lineage, covered session
  range, and predecessor provenance through the shared Publication contract.
- [x] The Release and Publication manifest become visible in one PostgreSQL
  commit, after all immutable objects exist.
- [x] The canonical Web Shell exposes navigation for the four resources and the
  Data page owns its loading, empty, refresh, updating, published, and error
  states through the real Core HTTP interface.
- [x] The Data page moves from updating to published and shows the first Release
  without provider mode, object key, manifest internals, or raw JSON.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/adapters \
  tests/integration \
  tests/acceptance/test_core_fixture_data_update.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:core
./scripts/core-test-runtime down
```

The tests must drive Data Update through the canonical Core HTTP and worker
entrypoints, PostgreSQL, Publication, and RustFS. They must also drive the Data
page through updating and published states. No legacy `/api/v1` Fixture publish
endpoint counts as Ticket 10 verification.

## Comments

- TDD red: the adapter contract test failed at collection because the canonical
  Core had no `thesistrace.adapters.fixture_data` implementation.
- `POST /api/data/update` writes only the accepted receipt and `updating` state.
  The separately wired Core worker claims that receipt, records its Attempt,
  collects the Fixture batch, validates it, prepares immutable S3 objects, then
  commits the Publication records and Data Release in one PostgreSQL transaction.
- Fixture implements only `DataSource.collect(CollectionPlan)`. It returns
  canonical records and source lineage without any Release, database,
  Publication, ResearchRun, or DailyTrack concept.
- Data validates the 756 ordered Research Sessions, three-calendar-year span,
  canonical schema/tables, Liquidity Universe coverage, Field Catalog identity,
  and point-in-time reference intervals before publication.
- The stable `/data` route renders the canonical four-resource shell. Its Data
  page owns loading, empty, updating, published, failed, refresh, and action
  behavior through `/api/data`; it never calls the legacy `/api/v1` endpoint.
- Backend verification passed `15 passed, 1 warning`; focused architecture and
  restart regression passed `13 passed, 1 skipped`; Web shell test and build
  passed. Real Playwright acceptance from `/data` passed in `8.1s` against the
  isolated PostgreSQL/RustFS runtime and an independent API/worker process pair.
- Independent review passed Standards but rejected the first validation because
  empty Price tables and a missing Adjustment Anchor table could still pass.
  Data now requires complete Trading State coverage, Price/Limit coverage for
  every non-suspended instrument-session, required Price columns, complete Base
  Pool, Adjustment Anchor, Liquidity Universe and instrument identities, and
  valid point-in-time intervals. Five adapter/validation tests pass, including
  explicit empty-table, missing-anchor, and missing-column rejection cases; the
  real Core acceptance still passes with the complete Fixture batch.
- Re-review found that Cartesian key sets would consume GB-scale extra memory
  for the real A-share universe and that several value contracts were still
  permissive. Validation now streams the canonical Trading State order and
  aligns Price/Limit rows without full key sets. Ten adapter tests now reject
  null/non-numeric Price or Anchor values, missing Price/Limit fields, invalid
  PIT dates, and unknown Industry instruments; the valid real publication path
  continues to pass.
- Final independent re-review: `Standards: PASS`, `Spec: PASS`. The exact
  backend command passed `24 passed, 1 warning` in `12.39s`.
- The final browser pass exposed and closed an acceptance-startup race:
  Playwright now waits independently for Core API readiness and Vite readiness
  before opening `/data`. The final real browser run passed in `7.8s`, and the
  ticket command then shut down and removed the isolated runtime.
- The first default gate also exposed that the isolated acceptance lacked the
  repository's standard environment skip. It now skips only when Core
  PostgreSQL/RustFS variables are absent and still executes under the ticket
  command. Final `make check` passed with Ruff clean, `491 passed, 35 skipped,
  2 warnings` in Python (`500.43s`), Web typecheck/build green, and the existing
  narrow/desktop Playwright flows passing in `30.8s` and `30.0s`.
