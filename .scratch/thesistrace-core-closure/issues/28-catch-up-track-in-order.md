# 28 — Catch up a DailyTrack in order

**What to build:** Let a lagging DailyTrack process every already-published
successor Dataset Release one at a time without skipping a boundary.

**Blocked by:** 27.

**Status:** ready-for-agent

- [ ] Each progression targets only the direct successor of the committed Head.
- [ ] A successful progression makes the following successor eligible until
  Head reaches the current latest Release.
- [ ] The Track never jumps directly to latest, merges targets, or skips a
  failed target.
- [ ] Every intermediate Checkpoint is independently committed and verified.
- [ ] A failure leaves Head at the last successful Release and stops catch-up at
  that exact target.
- [ ] Dataset publication catch-up and DailyTrack progression catch-up remain
  separate concepts and neither waits for the other.

**How to verify:**

- Run `uv run pytest -q tests/integration tests/acceptance` with at least three
  ordered successor Releases and inspect every committed intermediate Head.
- Confirm a failure at the middle target leaves later Releases published but
  unprocessed by that Track.

## Comments
