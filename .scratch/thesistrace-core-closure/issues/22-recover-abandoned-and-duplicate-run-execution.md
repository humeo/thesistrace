# 22 — Recover abandoned and duplicate ResearchRun execution

**What to build:** Recover one ResearchRun after worker loss or duplicate
delivery without creating a duplicate terminal result.

**Blocked by:** 20.

**Status:** ready-for-agent

**Implementation:** complete

- [x] Multiple workers cannot simultaneously own the same live claim.
- [x] An abandoned eligible claim becomes recoverable after its lease and
  process state are no longer valid.
- [x] Duplicate delivery produces at most one terminal state and one visible
  Result reference.
- [x] A stale worker cannot publish or change lifecycle state after losing its
  fence.
- [x] Worker restart recovers queued or eligible running work from PostgreSQL
  without creating a new ResearchRun.
- [x] Claim, Attempt, lease, heartbeat, and recovery details never enter the
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

- ResearchRuns now owns a renewable PostgreSQL Attempt lease. A private
  heartbeat extends only the live Attempt whose Run and execution fence still
  match; a second worker treats that live claim as a no-op.
- Claiming locks the Run row with `FOR UPDATE OF run SKIP LOCKED`. Recovery
  marks one expired running Attempt abandoned, increments the fence, and
  creates the next Attempt in the same transaction. The existing partial
  unique index continues to enforce at most one running Attempt per Run.
- A fresh runtime recovers queued or expired running work directly from
  PostgreSQL under the same ResearchRun ID. Success and failure writes retain
  their fence checks, so a stale prepared worker cannot publish a Result or
  overwrite the winning terminal lifecycle state.
- Four acceptance scenarios use real PostgreSQL and RustFS: restart recovery
  after simulated process loss, two-worker live-claim exclusion plus duplicate
  delivery, observed heartbeat renewal beyond the initial lease, and stale
  prepared-worker fencing after a recovered winner. They also assert one
  Result manifest at most and no internal execution fields in HTTP detail.
- The final ticket command written above passed `17 passed, 1 warning` in
  `28.69s`; its final `down` step removed the isolated test containers.
- Independent review passed `Standards: PASS` and `Spec: PASS` with no
  findings. It confirmed the row lock plus partial unique index, transactional
  recovery, heartbeat and terminal fence checks, duplicate no-op behavior,
  same-ID restart recovery, single visible Result, and ticket-local copy/paste
  verification command.
- The final repository `make check` invocation exited `0`: Ruff passed, Python
  passed `521 passed, 67 skipped, 2 warnings` in `607.05s`, Web typecheck and
  production build passed, and narrow/desktop Playwright each passed in
  `32.5s` and `32.3s`.
