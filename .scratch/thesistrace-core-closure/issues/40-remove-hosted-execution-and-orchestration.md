# 40 — Remove Hosted execution and orchestration

**What to build:** Delete the inactive Temporal, dispatch, outbox, relay, and
Hosted worker execution path while preserving canonical PostgreSQL workers.

**Blocked by:** 01, 38.

**Status:** ready-for-agent

- [ ] The Hosted archive ref is reverified before deletion.
- [ ] Temporal workflows, activities, task queues, execution relay, dispatch
  queue, outbox, and Hosted compute workers are removed with their callers.
- [ ] Hosted-only execution entrypoints, dependencies, targets, and tests are
  removed in the same contraction.
- [ ] Remaining Hosted operations and deployment files no longer import or
  invoke the removed execution path, without deleting those files early.
- [ ] Core ResearchRun and DailyTrack execution continue only through their
  PostgreSQL-owned processors.
- [ ] No active source, configuration, or default gate imports or starts the
  removed orchestration path.
- [ ] Accepted quantitative behavior and immutable publications remain
  unchanged.

**How to verify:**

- Run `uv run pytest -q tests/architecture tests/integration tests/acceptance`
  with no Temporal service or Hosted worker available.
- Inspect the dependency and entrypoint inventory; every removed execution
  component must have no remaining active caller.

## Comments
