---
status: accepted
---

# Run four single-slot Compute Worker containers

The first Hosted Platform V2 Compose deployment runs four identical,
long-lived Compute Worker containers. Each Temporal Worker accepts at most one
heavy Compute Activity at a time, so the four containers implement the initial
global Compute concurrency of four defined by ADR-0115.

Compute concurrency is changed through deployment configuration and worker
replica count, not through a product or research-domain setting. The first
deployment does not execute multiple heavy Activities inside one Compute
Worker process and does not create a new container for each job. It therefore
needs neither privileged Docker access nor a nested job-container scheduler.

Each Compute Worker receives an independent CPU, memory, and temporary-storage
limit. A process crash or out-of-memory termination affects its current
Activity rather than all four Compute slots; Temporal may retry the Activity
under its bounded retry policy, while application idempotency and final-commit
fencing remain authoritative. Representative capacity tests must show that one
accepted workload fits within one Worker's limits before concurrency four is
enabled for invited Users.

The one-slot Data Worker remains a separate container and Task Queue under
ADR-0116. It may run concurrently but does not consume a Compute slot. Compute
Workers are shared across Personal Workspaces and rely on ADR-0145 priority
followed by Temporal fairness; the first hosted release does not dedicate a
container or process to each User.

Concrete container resource values are a separate deployment-capacity
decision.
