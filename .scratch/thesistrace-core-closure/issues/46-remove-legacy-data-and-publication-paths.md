# 46 — Remove legacy Data and Publication paths

**What to build:** Delete the old Data lifecycle, persistence, source-selection,
and publication paths after the canonical Data and Publication modules own the
complete product path.

**Blocked by:** 45.

**Status:** ready-for-agent

- [ ] Old Data Update, Release, source-selection, and publication callers are
  removed without deleting the canonical DataSource adapters.
- [ ] Old filesystem object, metadata facade, release mutation, and provider-mode
  publication entrypoints have no remaining caller.
- [ ] Legacy Data and publication tests are removed or migrated to the canonical
  Data product and shared Publication contracts.
- [ ] No fallback can publish a Dataset Release through SQLite, filesystem
  objects, a custom server, or an old source-specific route.
- [ ] Canonical Fixture and Tushare DataSource adapters, PostgreSQL Releases,
  standard S3 Publication, verified reads, and Data Web behavior remain
  unchanged.
- [ ] Shared canonical-data and quantitative code still used by the Core is
  preserved rather than deleted with its old caller.

**How to verify:**

- Run `uv run pytest -q tests/architecture tests/adapters tests/integration tests/acceptance`
  with every legacy Data and publication entrypoint absent.
- Run `bun run --cwd web test:e2e` and confirm first, later, no-change, and
  failed Data outcomes still use the canonical path.

## Comments
