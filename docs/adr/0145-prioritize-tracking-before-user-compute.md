---
status: accepted
---

# Prioritize Tracking before User Compute

Hosted Platform V2 prefers P1 automatic Tracking Advances over P3 ResearchRuns and explicit equivalence verification, with Personal Workspace fairness inside each tier and no preemption of running Activities. When both tiers are queued, one of the four Compute slots guarantees P3 progress while the other three prefer P1; when either tier is empty, all four slots remain work-conserving for the other tier. Dataset Publication stays on its separate Data Worker Task Queue.
