---
status: accepted
---

# Use Temporal for durable orchestration and fair dispatch

Hosted Platform V2 uses Temporal as its only durable orchestration and fair-dispatch engine, replacing the proposed custom Scheduler, PostgreSQL claim loop, leases, retry timers, and scheduled trigger with finite Workflows and role-specific Activities. InsForge PostgreSQL remains authoritative for product truth, while an execution outbox starts Temporal idempotently and Temporal Workflow History records execution state only. This separation avoids duplicate schedulers and unbounded Workflows while preserving Personal Workspace fairness and independent Dataset Publication execution.
