---
status: accepted
---

# Pause admission and drain Activities during maintenance

Before a Hosted Platform V2 maintenance release changes steady services, Caddy
enters maintenance mode and the Control Plane stops accepting new ResearchRun,
Tracking, equivalence-verification, and Dataset Publication admissions.
The operator pauses Temporal Schedules and the execution-outbox relay so no new
Workflow Execution begins during the migration boundary.

Running Activities receive up to 15 minutes to finish. After that drain period,
Workers shut down normally even if an Activity remains incomplete. The
corresponding domain Attempt stays nonterminal: maintenance does not mark it
failed or cancelled and does not consume the bounded
`RESOURCE_EXHAUSTED` retry in ADR-0132. Temporal may redeliver the incomplete
Activity after compatible Workers return, while application idempotency,
staging cleanup, and final-commit fencing prevent duplicate publication.

If ADR-0109 requires a result-changing Tracking Generation rebuild, it runs
only after ordinary work drains and while admissions, Schedules, and the
execution-outbox relay remain paused. The operator does not resume normal P1/P3
dispatch until that exceptional maintenance boundary succeeds or is safely
abandoned with the previous Generation and Head unchanged.

After migrations and steady services succeed, the operator starts Workers,
reconciles the execution outbox, resumes Temporal Schedules, and removes the
public maintenance response only after the accepted health checks pass.
Dataset Publication catch-up processes eligible market sessions missed during
the maintenance interval; it does not synthesize a separate Release for the
maintenance event.
