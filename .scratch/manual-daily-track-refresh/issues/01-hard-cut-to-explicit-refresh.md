# 01 — Hard-cut DailyTrack to explicit Refresh

**Status:** ready-for-agent

**What to build:** Replace Dataset-Head-driven automatic Tracking Advances with
one idempotent explicit Refresh command across Product State, Worker claiming,
HTTP, MCP, and Web.

- [ ] Activation leaves a DailyTrack idle.
- [ ] Head movement alone cannot queue or claim a Tracking Advance.
- [ ] Refresh queues exactly one Advance and has durable idempotency receipts.
- [ ] Existing bounded retry, blocked Retry, Stop, fencing, and Checkpoint
      publication remain intact inside an accepted Advance.
- [ ] HTTP and MCP expose Refresh with consistent authority and errors.
- [ ] DailyTrack Detail separates Refresh from Reload and polls bounded active
      operations only.
- [ ] Domain docs, ADRs, architecture, and tests describe explicit Refresh.
- [ ] Focused backend, MCP, frontend, and real-browser verification pass.

## Comments

- No migration or compatibility behavior is permitted; the current schema and
  contracts are replaced directly.
- 2026-08-29 isolated PostgreSQL/RustFS smoke advanced the Dataset Head from
  `2026-08-05` to `2026-08-06` with two active Tracks. Before explicit Refresh,
  Tracking Worker claimed no work and both Tracks reported `waiting`, lag `1`.
  After one Refresh per Track, both Advances succeeded at `2026-08-06`; each
  Track persisted exactly two Checkpoints, one Progression, one Attempt, and one
  Refresh receipt, with no queued work left. The current `thesistrace-dev`
  database remains untouched because it is an older unsupported schema with one
  existing Track; browser verification requires an explicit Development reset
  decision.
