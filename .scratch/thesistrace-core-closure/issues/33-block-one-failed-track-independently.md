# 33 — Block one failed DailyTrack independently

**What to build:** Move only the affected DailyTrack to blocked after its
automatic progression retries are exhausted while Data and other Tracks keep
working.

**Blocked by:** 28.

**Status:** ready-for-agent

- [ ] Exhausted automatic retry changes the affected Track to `blocked`, records
  a sanitized readable reason, and preserves its last successful Head.
- [ ] Its current failed target remains fixed even when newer Releases appear.
- [ ] Data continues to publish later Dataset Releases without waiting for the
  blocked Track.
- [ ] Other active DailyTracks continue to discover and advance successor
  Releases.
- [ ] Process restart preserves enough PostgreSQL and Publication truth to
  retry or stop the blocked Track.
- [ ] The Web shows blocked status and reason without exposing Attempt, claim,
  or worker diagnostics.

**How to verify:**

- Run `uv run pytest -q tests/integration tests/acceptance` with two Tracks and
  a deterministic failure affecting only one target of one Track.
- Publish a later Release and restart the worker; confirm Data and the other
  Track progress while the failed Track keeps its previous Head and target.

## Comments
