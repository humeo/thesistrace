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

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/integration \
  tests/acceptance/test_core_research_run_recovery.py
./scripts/core-test-runtime down
```

The tests must use real PostgreSQL and RustFS with two ResearchRun service
instances to prove exclusive live ownership, duplicate processing as a no-op,
expired-lease recovery after worker loss, stale-fence rejection after recovery,
and fresh-runtime restart recovery of the same ResearchRun identity. The public
HTTP detail must end with at most one visible Result and contain no Attempt,
claim, lease, heartbeat, fence, or recovery fields.

## Comments
