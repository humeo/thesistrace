---
status: accepted
---

# Deploy Hosted Platform V2 on one Compose node first

Hosted Platform V2 initially deploys on one 6-core, 12-GB node with a 200-GB persistent SSD and Docker Compose, while its Control, Scheduling, Data, and Compute planes remain logically isolated by process or container boundaries. This minimizes launch operations within the measured capacity envelope and preserves later scale-out seams, but deliberately provides no high availability.
