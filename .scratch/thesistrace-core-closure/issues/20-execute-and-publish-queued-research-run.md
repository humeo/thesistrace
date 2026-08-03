# 20 — Execute and publish one queued ResearchRun

**What to build:** Move one queued ResearchRun through its PostgreSQL-owned
worker and pure Kernel to one durable, completely published success.

**Blocked by:** 19.

**Status:** ready-for-agent

- [ ] A ResearchRuns-owned processor claims queued work and projects it as
  `running`; no global job table, dispatch command, or outbox is involved.
- [ ] The worker loads only the pinned Release through Data's canonical loader
  and executes the stored immutable input through Kernel Run.
- [ ] It prepares the Result through shared Publication and commits the verified
  reference with `succeeded` under the current fence.
- [ ] Result provenance binds the ResearchRun immutable input, pinned Dataset
  Release, calculation contracts, and Kernel semantic versions through the
  shared Publication contract.
- [ ] Publication failure or a stale fence exposes no partial Result and cannot
  record success.
- [ ] Attempt, claim, lease, heartbeat, and object details remain private.
- [ ] ResearchRun list and detail retain the queued, running, and succeeded
  product projections across HTTP and worker restart.

**How to verify:**

- Run `uv run pytest -q tests/integration tests/acceptance` against real
  PostgreSQL and RustFS and observe one admitted Run reach succeeded.
- Restart the HTTP process after completion and confirm the same Run and
  verified publication reopen without executing again.

## Comments
