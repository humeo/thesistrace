---
status: superseded by ADR-0151
---

# Run four single-slot Compute Worker containers

Hosted Platform V2 runs four identical long-lived Compute Worker containers, each accepting at most one heavy Compute Activity, while the one-slot Data Worker remains separate. Independent single-slot workers bound global Compute concurrency and isolate a process or memory failure without requiring privileged Docker access or one container per job.
