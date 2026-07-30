# 09 — Enforce the Personal Workspace Quota Profile

**What to build:** Give each Personal Workspace one auditable Quota Profile and
enforce its nonterminal User Compute dimension at admission so retries remain
idempotent and one User cannot build an unbounded queue.

**Blocked by:** 05 — Consume an invitation and provision one Personal Workspace; 07 — Run one Research Workflow through Temporal.

**Status:** ready-for-agent

- [ ] Every Personal Workspace resolves one effective Quota Profile containing only `max_active_daily_tracks`, `max_nonterminal_user_compute_jobs`, and `max_private_storage_bytes`.
- [ ] The deployment defaults are an Active DailyTrack hard maximum of `10`, at most `8` nonterminal User Compute jobs, and `10 GiB` of private immutable storage.
- [ ] A new ResearchRun or rerun is rejected before durable execution admission when the Workspace already has eight queued or running User Compute jobs; the same admission port is available to later P3 operations.
- [ ] Idempotent request retries return the existing resource and do not count as new quota consumption.
- [ ] A quota rejection identifies the exceeded dimension and remains distinguishable from API rate limiting, disk pressure, research validation, and Worker resource exhaustion.
- [ ] The Operator CLI records sanitized audit events for explicit overrides; an active-Track override may only lower the deployment hard maximum.
- [ ] Quota changes govern later admissions and writes without cancelling running work, deleting retained history, or charging platform-owned Dataset Releases to a Personal Workspace.
