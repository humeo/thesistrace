---
status: accepted
---

# Admit heavy work through a configurable scheduling limit

Hosted Platform V2 queues ResearchRuns, Tracking Advances, and equivalence
verification as Temporal Workflows and Activities before execution.
Public API requests create durable domain work and an execution outbox entry;
they do not perform these calculations synchronously. An idempotent relay starts
the corresponding Temporal Workflow.

The Compute Activity worker pool runs no more than the deployment's configured
global compute concurrency, whose initial 6-core, 12-GB value is four.

The value is an operator capacity setting, not a domain or API contract, and may
change without altering research semantics. Production acceptance must prove
the configured value against representative workloads and resource limits.
Every job retains durable domain Attempt, cancellation, and late-publication
fencing semantics. Temporal owns task delivery, retries, Activity heartbeats,
timeouts, and crash recovery; ThesisTrace does not run a parallel PostgreSQL
claim-and-lease scheduler.

Compute Activities use the Personal Workspace identity as their Temporal
fairness key with equal weight. Dispatch is work-conserving and prevents one
Workspace backlog from starving others while allowing active Workspaces to use
otherwise idle capacity. This accepts Temporal's fairness semantics rather than
promising strict one-opportunity-per-Workspace rounds: fairness is applied at
Task Queue dispatch and does not retroactively include Activities that have
already been dispatched.

ADR-0145 applies two priority tiers before that Workspace fairness: automatic
Tracking Advances use P1, while ResearchRuns and explicit equivalence
verification use P3. The first node keeps this low-throughput Compute Activity
Task Queue at one partition so the accepted platform-level ordering is not
weakened by cross-partition dispatch.

Dataset Publication follows the separate platform execution model in ADR-0116
and does not consume this configured Compute concurrency.
