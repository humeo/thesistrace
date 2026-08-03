# 36 — Harden DailyTrack activation admission

**What to build:** Make Start Tracking concurrency-safe, idempotent, and
bounded after the first DailyTrack activation path already works.

**Blocked by:** 26.

**Status:** ready-for-agent

- [ ] ResearchRuns records its Start Tracking receipt and calls private
  DailyTrack activation in one PostgreSQL transaction; failure leaves neither a
  receipt nor a partial Track.
- [ ] DailyTracks enforces one Track per seed ResearchRun under concurrent
  activation without ResearchRuns reading DailyTrack tables.
- [ ] Activation is allowed when the current active-or-blocked count is below
  ten, the tenth Track succeeds, and the eleventh is rejected; stopped Tracks
  do not count.
- [ ] Matching request replay returns the originally activated DailyTrack.
- [ ] Reusing a request ID with different action input returns a conflict, and a
  structurally malformed request creates no receipt.
- [ ] Duplicate-seed, limit, replay, conflict, and rollback outcomes are visible
  as product action results without exposing transaction or Activation
  Checkpoint internals.

**How to verify:**

- Run `uv run pytest -q tests/integration tests/acceptance` with concurrent
  duplicate activation, transaction rollback, replay, conflict, malformed
  input, the successful tenth Track, and the rejected eleventh Track.
- Run `bun run --cwd web test:e2e` and confirm the Run detail returns the same
  Track on replay and shows the duplicate or limit outcome without a partial
  resource.

## Comments
