# 34 — Retry the same failed DailyTrack target

**What to build:** Let a user retry exactly the Dataset Release progression that
blocked a DailyTrack, then resume ordered catch-up only after that target
succeeds.

**Blocked by:** 29, 33.

**Status:** ready-for-agent

- [ ] Retry is accepted only for a blocked Track and always addresses its
  existing failed target.
- [ ] It cannot select, skip to, or merge a newer Dataset Release.
- [ ] Success moves Head to the original target, returns the Track to `active`,
  and makes the next direct successor eligible.
- [ ] Another failure preserves `blocked`, its prior Head, and the same target.
- [ ] Matching request replay returns the original action outcome; different
  input with the same request ID conflicts.
- [ ] A structurally malformed Retry creates no action receipt.
- [ ] The Web exposes Retry and its resulting product state without internal
  Attempt controls.

**How to verify:**

- Run `uv run pytest -q tests/integration tests/acceptance` with successful,
  repeated, conflicting, malformed, and repeatedly failing Retry cases.
- Run `bun run --cwd web test:e2e` and confirm Retry first reaches the old target
  before ordered catch-up continues.

## Comments
