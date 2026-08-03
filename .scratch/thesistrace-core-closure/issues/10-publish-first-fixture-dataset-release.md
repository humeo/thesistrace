# 10 — Publish the first Fixture Dataset Release

**What to build:** Let a user request Data Update and later see the first
immutable Fixture Dataset Release through the canonical Web, HTTP, worker,
PostgreSQL, Publication, and RustFS path.

**Blocked by:** 06.

**Status:** ready-for-agent

- [ ] Data Update durably returns `accepted` without waiting for collection or
  publication.
- [ ] A Data-owned worker claims the request and performs the first three-year
  Bootstrap from the canonical Fixture adapter.
- [ ] Fixture implements only the DataSource collection and canonical mapping
  contract; it knows no Release ID, PostgreSQL, S3, ResearchRun, or DailyTrack.
- [ ] Data validates coverage, schema, point-in-time, calendar, and publication
  rules before creating an immutable Dataset Release.
- [ ] Data supplies canonical contract, collection lineage, covered session
  range, and predecessor provenance through the shared Publication contract.
- [ ] The Release and Publication manifest become visible in one PostgreSQL
  commit, after all immutable objects exist.
- [ ] The canonical Web Shell exposes navigation for the four resources and the
  Data page owns its loading, empty, refresh, updating, published, and error
  states through the real Core HTTP interface.
- [ ] The Data page moves from updating to published and shows the first Release
  without provider mode, object key, manifest internals, or raw JSON.

**How to verify:**

- Run `uv run pytest -q tests/adapters tests/integration tests/acceptance`
  against clean PostgreSQL and an empty RustFS bucket.
- Run `bun run --cwd web test:e2e` and confirm one visible Data Update reaches a
  published first Release through the real worker and the reusable isolated
  PostgreSQL/RustFS runtime from ticket 03.

## Comments
