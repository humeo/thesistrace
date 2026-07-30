---
status: accepted
---

# Admit heavy work through a configurable scheduling limit

Hosted Platform V2 admits ResearchRuns, Tracking Advances, and equivalence verification asynchronously through finite Temporal Workflows and a deployment-configured global Compute concurrency limit, with fair dispatch keyed by Personal Workspace after the accepted priority tier. This bounds resource use and prevents one Personal Workspace backlog from monopolizing Compute capacity while leaving Dataset Publication on its separate execution path.
