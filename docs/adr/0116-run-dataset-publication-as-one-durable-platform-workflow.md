---
status: accepted
---

# Run Dataset Publication as one durable platform workflow

Hosted Platform V2 does not put Dataset Publication in the Personal Workspace
Compute Task Queue. A Temporal Schedule or an authorized manual request starts
one finite Publication Workflow, and one dedicated Data Worker executes at most
one Publication Activity at a time. The domain lifecycle and Attempts remain
visible in PostgreSQL while Temporal provides durable timers, task delivery,
heartbeat, retry, cancellation, and crash recovery. Catch-up behavior remains
Dataset Publication domain logic.

The PostgreSQL record is product state, and Temporal Workflow History is
execution state; neither replaces the other. The transactional execution outbox
bridges their commit boundary and is not a general-purpose Data Queue or message
broker. ThesisTrace does not maintain a second PostgreSQL claim-and-lease loop.
The configured Compute concurrency in ADR-0115 excludes Dataset Publication.

The Data Worker may execute concurrently with Compute Workers and receives an
independent container CPU, memory, and temporary-storage budget. Compute
capacity is validated and configured only after reserving resources for the
Control Plane, PostgreSQL, and Data Worker. Publication neither waits behind the
Personal Workspace Compute queue nor preempts running Compute jobs. Concrete
resource values come from representative capacity tests rather than this ADR.
