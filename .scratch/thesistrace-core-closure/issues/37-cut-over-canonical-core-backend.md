# 37 — Cut over the canonical Core backend

**What to build:** Make the module-first HTTP and worker composition the only
active backend path while leaving old source present but unreachable for later
controlled contraction.

**Blocked by:** 12, 13, 14, 23, 24, 25, 31, 32, 34, 35, 36.

**Status:** ready-for-agent

- [ ] Every public resource URL and action resolves only through the new Data,
  Definitions, ResearchRuns, and DailyTracks modules.
- [ ] Worker startup invokes only module-owned Data, ResearchRun, and DailyTrack
  processors.
- [ ] Active assembly contains no Local/Hosted selection, authentication,
  SQLite, Temporal, outbox, relay, or global dispatch branch.
- [ ] Product modules use declared private interfaces rather than cross-schema
  SQL, global metadata, or Hosted imports.
- [ ] The same configuration shape addresses PostgreSQL and any standard
  S3-compatible endpoint without choosing a product mode.
- [ ] Old backend paths remain in the tree only as unreachable contraction
  targets; this ticket deletes none of them.
- [ ] Restarting the canonical HTTP and workers preserves all four product
  resources and authoritative publications.

**How to verify:**

- Run `uv run pytest -q tests/architecture tests/integration tests/acceptance`
  with only the canonical entrypoints enabled.
- Inspect running processes and request traces while exercising all resource
  actions; no old, Hosted, SQLite, or Temporal backend may execute.

## Comments
