# 13 — Orchestrate Equivalence and Generation rebuilds

**What to build:** Run explicit Batch-Incremental Equivalence and
maintenance-only result-changing Tracking Generation rebuilds as separate,
finite, durable operations without turning Temporal history into DailyTrack
product truth.

**Blocked by:** 12 — Advance DailyTrack through finite Workflows; `thesistrace-v1-research-platform/27 — Verify Batch-Incremental Equivalence over ordered Dataset Releases`.

**Status:** ready-for-agent

- [ ] An authorized User can request explicit equivalence asynchronously, receive one durable P3 User Compute resource, and inspect its bounded status and canonical success or first-divergence result.
- [ ] Equivalence shares the Personal Workspace limit of eight nonterminal User Compute jobs with ResearchRuns, idempotent retries do not consume another unit, and an Operator maintenance Generation rebuild is not charged as ordinary User Compute.
- [ ] Equivalence follows the immutable Checkpoint chain's exact ordered Dataset Release sequence and never substitutes one latest-Release replay.
- [ ] An authorized maintenance operation can create and fully execute a new Tracking Generation for a result-changing kernel fix without mutating the prior Generation.
- [ ] Both operations use finite Temporal Workflows with idempotent Activities, heartbeats, cooperative cancellation, and fenced final publication.
- [ ] Equivalence and Generation rebuild follow the shared resource-exhaustion policy: after at most one automatic retry, repeated exhaustion ends with stable `RESOURCE_EXHAUSTED` and publishes neither a partial verification result nor a partial Generation.
- [ ] PostgreSQL remains authoritative for request, ownership, lifecycle, and published result; Workflow History contains only orchestration state and opaque control identities.
- [ ] Repeating one idempotent request cannot duplicate an equivalence resource or Generation rebuild, while a deliberate rerun creates a new domain request.
- [ ] Cross-Personal-Workspace identifiers and non-Operator Generation rebuild attempts receive sanitized non-disclosing denial.
