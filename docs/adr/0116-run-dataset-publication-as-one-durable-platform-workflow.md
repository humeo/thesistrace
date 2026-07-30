---
status: accepted
---

# Run Dataset Publication as one durable platform workflow

Dataset Publication runs as one finite Temporal Workflow on a dedicated single-slot Data Worker, started by a Temporal Schedule or authorized manual request and kept outside the Personal Workspace Compute queue. PostgreSQL remains the publication product record while Temporal owns durable execution, avoiding competition for Personal Workspace Compute capacity and a duplicate PostgreSQL claim-and-lease scheduler.
