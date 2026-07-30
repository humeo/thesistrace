# 15 — Dispatch P1 and P3 work fairly

**What to build:** Use Temporal's real dispatch path to prefer automatic P1
Tracking while guaranteeing bounded P3 User Compute progress, preserving
same-tier Personal Workspace fairness and using every otherwise idle Compute
slot.

**Blocked by:** 09 — Enforce the Personal Workspace Quota Profile; 13 — Orchestrate Equivalence and Generation rebuilds; 14 — Lock down the five-Worker topology.

**Status:** ready-for-agent

- [ ] Global heavy Compute concurrency never exceeds the configured four slots, and Dataset Publication remains on the independent one-slot Data Worker.
- [ ] While P1 and P3 remain queued together, at least one active or next-available Compute slot makes P3 progress while the other three prefer P1.
- [ ] When either tier has no queued work, the other tier can use all four slots without an artificial reservation leaving capacity idle.
- [ ] Equal-weight Personal Workspace fairness and FIFO ordering apply within each priority tier so one Workspace backlog cannot monopolize dispatch.
- [ ] A later higher-priority request never preempts an already running Activity.
- [ ] Dispatch uses Temporal Task Queues and Worker polling rather than a PostgreSQL claim-and-lease loop, retry timer, or second custom scheduler.
- [ ] A real Temporal deterministic probe repeats the same controlled input schedule and obtains the same dispatch decisions, including sustained P1 and P3 backlogs.
