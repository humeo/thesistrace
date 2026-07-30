# 09 — Enforce the Personal Workspace Quota Profile

**What to build:** Give each Personal Workspace one auditable Quota Profile and
enforce its nonterminal User Compute dimension at admission so retries remain
idempotent and one User cannot build an unbounded queue.

**Blocked by:** 05 — Consume an invitation and provision one Personal Workspace; 07 — Run one Research Workflow through Temporal.

**Status:** complete

- [x] Every Personal Workspace resolves one effective Quota Profile containing only `max_active_daily_tracks`, `max_nonterminal_user_compute_jobs`, and `max_private_storage_bytes`.
- [x] The deployment defaults are an Active DailyTrack hard maximum of `10`, at most `8` nonterminal User Compute jobs, and `10 GiB` of private immutable storage.
- [x] A new ResearchRun or rerun is rejected before durable execution admission when the Workspace already has eight queued or running User Compute jobs; the same admission port is available to later P3 operations.
- [x] Idempotent request retries return the existing resource and do not count as new quota consumption.
- [x] A quota rejection identifies the exceeded dimension and remains distinguishable from API rate limiting, disk pressure, research validation, and Worker resource exhaustion.
- [x] The Operator CLI records sanitized audit events for explicit overrides; an active-Track override may only lower the deployment hard maximum.
- [x] Quota changes govern later admissions and writes without cancelling running work, deleting retained history, or charging platform-owned Dataset Releases to a Personal Workspace.

**Acceptance evidence:** Every provisioned Personal Workspace now receives the
three-field default profile, and the Operator CLI can inspect or partially
override it while recording the changed dimensions and explicit values in the
management audit log. PostgreSQL serializes partial overrides with a row lock,
so concurrent changes to different dimensions are both retained. ResearchRun
and rerun admission use a Workspace-scoped advisory lock, an RLS-protected
nonterminal admission ledger, and an idempotency lock before the durable Run
and Outbox commit. Terminal completion or cancellation releases the admission.
The API reports quota pressure as `409 QUOTA_EXCEEDED` with the dimension and
limit, distinct from `429`, validation, disk, and Worker exhaustion responses.
The real Hosted Compose/PostgreSQL acceptance admitted exactly eight
nonterminal Runs, returned one existing Run for two concurrent uses of the
same idempotency key, rejected the ninth, admitted replacement work after
cancellation, preserved two concurrent profile overrides, and exposed zero
admissions through a second Workspace identity. Focused tests passed `23`
tests with `3` environment-gated skips; the complete Python suite passed `117`
tests with `7` environment-gated skips. Independent Standards and Spec reviews
both passed after the audit-detail, concurrent-update, least-privilege, and API
response-deduplication corrections.
