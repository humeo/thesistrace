# 22 — Recover abandoned and duplicate ResearchRun execution

**What to build:** Recover one ResearchRun after worker loss or duplicate
delivery without creating a duplicate terminal result.

**Blocked by:** 20.

**Status:** ready-for-agent

- [ ] Multiple workers cannot simultaneously own the same live claim.
- [ ] An abandoned eligible claim becomes recoverable after its lease and
  process state are no longer valid.
- [ ] Duplicate delivery produces at most one terminal state and one visible
  Result reference.
- [ ] A stale worker cannot publish or change lifecycle state after losing its
  fence.
- [ ] Worker restart recovers queued or eligible running work from PostgreSQL
  without creating a new ResearchRun.
- [ ] Claim, Attempt, lease, heartbeat, and recovery details never enter the
  product projection.

**How to verify:**

- Run `uv run pytest -q tests/integration` with concurrent workers, duplicate
  delivery, lease expiry, stale publication, and process restart.
- Confirm the public ResearchRun remains one identity with at most one visible
  Result and no internal recovery fields.

## Comments
