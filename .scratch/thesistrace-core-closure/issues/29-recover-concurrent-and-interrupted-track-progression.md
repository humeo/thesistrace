# 29 — Recover concurrent and interrupted Track progression

**What to build:** Recover DailyTrack progression after duplicate workers,
stale claims, or process restart without publishing the same target twice.

**Blocked by:** 28.

**Status:** ready-for-agent

- [ ] PostgreSQL permits only one live owner for a Track and target Release.
- [ ] Two workers cannot publish or move Head for the same progression twice.
- [ ] A stale worker cannot move Head after its claim or fence is replaced.
- [ ] Worker restart recovers eligible unfinished work from durable Track and
  progression state.
- [ ] Recovery advances Head at most once for each target and then resumes
  ordered catch-up.
- [ ] Claim, Attempt, fence, and recovery fields remain absent from DailyTrack
  list and detail.

**How to verify:**

- Run `uv run pytest -q tests/integration` with concurrent claims, duplicate
  delivery, stale publication, worker termination, and restart.
- Inspect product state after recovery and confirm one Checkpoint and one Head
  movement exist for each target.

## Comments
