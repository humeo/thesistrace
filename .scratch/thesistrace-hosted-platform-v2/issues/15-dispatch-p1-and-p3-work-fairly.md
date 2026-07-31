# 15 — Dispatch P1 and P3 work fairly

**What to build:** Use Temporal's real dispatch path to prefer automatic P1
Tracking while guaranteeing bounded P3 User Compute progress, preserving
same-tier Personal Workspace fairness and using every otherwise idle Compute
slot.

**Blocked by:** 09 — Enforce the Personal Workspace Quota Profile; 13 — Orchestrate Equivalence and Generation rebuilds; 14 — Lock down the five-Worker topology.

**Status:** resolved

- [x] Global heavy Compute concurrency never exceeds the configured four slots, and Dataset Publication remains on the independent one-slot Data Worker.
- [x] While P1 and P3 remain queued together, at least one active or next-available Compute slot makes P3 progress while the other three prefer P1.
- [x] When either tier has no queued work, the other tier can use all four slots without an artificial reservation leaving capacity idle.
- [x] Equal-weight Personal Workspace fairness and FIFO ordering apply within each priority tier so one Workspace backlog cannot monopolize dispatch.
- [x] A later higher-priority request never preempts an already running Activity.
- [x] Dispatch uses Temporal Task Queues and Worker polling rather than a PostgreSQL claim-and-lease loop, retry timer, or second custom scheduler.
- [x] A real Temporal deterministic probe repeats the same controlled input schedule and obtains the same ThesisTrace-controlled tier/slot decisions, including sustained P1 and P3 backlogs; every run independently proves Temporal's accepted equal-weight Workspace bound and FIFO because exact cross-Workspace interleaving is intentionally approximate.

## Implementation

- Split heavy Activities into P1 and P3 Temporal Task Queues. Three single-slot
  Compute containers prefer P1 and one prefers P3, with backlog-driven
  work-conserving queue borrowing and graceful Worker shutdown so running work
  is never preempted.
- Enabled native Temporal fairness with equal Workspace weights and one matching
  partition. One serialized Workflow poller preserves durable relay FIFO while
  all four containers independently execute one heavy Activity.
- Added a real Temporal probe that reuses the production Compute and Data Worker
  builders. It verifies four Compute slots plus the independent Data slot,
  sustained 3:1 tier progress, same-tier fairness and FIFO, both borrowing
  directions, explicit later-P1 no-preemption, and repeated slot/tier decisions.
- Clarified the deterministic boundary in the spec and ADR: Temporal documents
  fairness as roughly proportional with small deviations, so exact
  cross-Workspace interleaving is checked by per-run invariants rather than
  treated as a repeatable decision.

## Verification

- `make hosted-dispatch-probe`
- `.venv/bin/python -m pytest -q tests/hosted` — `125 passed, 13 skipped`
- `.venv/bin/python -m pytest -q tests/hosted/test_compute_dispatch.py tests/hosted/test_compose_stack.py tests/hosted/test_dataset_publication_workflow.py` — `42 passed, 1 skipped`
- `.venv/bin/ruff check .`
- `bun run --cwd web typecheck`
- `bun run --cwd web build`
- Independent specification review: PASS
- Independent standards review: PASS
