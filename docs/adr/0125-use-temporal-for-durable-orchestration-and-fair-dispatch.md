---
status: accepted
---

# Use Temporal for durable orchestration and fair dispatch

Hosted Platform V2 uses Temporal as the Scheduling Plane's durable
orchestration and task-dispatch engine. This replaces the proposed custom
Scheduler, PostgreSQL job-claim loop, leases, retry timers, and scheduled
Publication trigger; it does not add Temporal beside those mechanisms.

InsForge PostgreSQL remains authoritative for identity, ownership, quota,
idempotency, product lifecycles, domain Attempts, and the mutable pointers to
immutable artifacts. An API transaction creates authorized domain work and an
execution outbox entry. A relay starts the corresponding Temporal Workflow
idempotently from a stable domain identity and reconciles an interrupted
handoff. Temporal Workflow History is execution state, not product truth.

Each operation uses a finite Workflow Execution:

- one Dataset Publication execution;
- one ResearchRun;
- one Tracking Advance;
- one maintenance-only Tracking Generation rebuild; or
- one equivalence verification.

A DailyTrack remains a PostgreSQL domain aggregate rather than one permanent
Workflow with unbounded history. Temporal Schedule triggers Publication, while
the Dataset Publication domain logic still determines market-session
eligibility and catch-up.

Workflow code only orchestrates deterministic state transitions. Side effects
and heavy calculation run as Activities in role-specific workers. Workflow and
Activity payloads contain only opaque resource identities, hashes, and small
control values; Tushare payloads, Dataset partitions, Alpha Matrices, Result
Bundles, and Tracking Checkpoints remain in PostgreSQL or object storage
according to their existing boundaries.

Compute Activities share one fair Task Queue, use Personal Workspace identity
as an equal-weight fairness key, and consume the deployment-configured worker
capacity. ADR-0145 assigns P1 or P3 before fairness and keeps the first
deployment's Compute Activity Queue at one partition. Publication uses a
separate Task Queue and a one-slot Data Worker, so it neither consumes tenant
Compute capacity nor waits behind it. Temporal's work-conserving fair dispatch
replaces the earlier strict round-by-round admission promise.

Activities may execute more than once. Every external write therefore remains
idempotent, long Activities heartbeat and respond cooperatively to
cancellation, and final Dataset latest, Result Bundle, and Tracking Head commits
retain PostgreSQL compare-and-set and late-publication fencing. Temporal does
not replace application authorization, quotas, disk-pressure admission,
container resource limits, data validation, or quantitative semantic checks,
and it does not make heavy computation faster.

ADR-0126 self-hosts the first Temporal Service on the Compose node. Moving that
service outside the node remains a later deployment change and does not alter
the orchestration boundary defined here.
