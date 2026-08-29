# 10 — Retain operation receipts without retaining Data Generations

**What to build:** Keep enough recent Data Refresh history for the Operator to
understand operational outcomes while ensuring that receipt retention cannot
silently become a Dataset Generation retention policy.

**Blocked by:** 08 — Cancel accepted work and Retry immutably; 09 — Recover Worker
claims and surface availability.

**Status:** ready-for-agent

- [ ] Non-terminal operation receipts are never removed by retention cleanup.
- [ ] Terminal published, no-change, degraded, failed, cancelled, and
  retry-exhausted receipts remain queryable for 180 days and become eligible for
  deterministic cleanup afterward.
- [ ] Cleanup preserves stable pagination and latest-operation-per-kind semantics
  for every receipt that remains visible.
- [ ] A receipt does not retain a Data Generation, add a Garbage Collection root,
  or prevent collection of otherwise unreachable Canonical or raw evidence.
- [ ] Removing an old receipt never changes the current Dataset Head, readiness,
  or a newer operation's state.
- [ ] Cleanup is idempotent, bounded, observable through safe counts, and does not
  expose deleted receipt contents or storage paths.
- [ ] Fixed-clock integration tests with real PostgreSQL and RustFS cover the
  180-day boundary, every terminal state, preservation of non-terminal work,
  repeated cleanup, pagination, and Generation collection.
- [ ] The Console handles a history page changing after cleanup without duplicate
  rows, broken cursors, or misleading empty state.
