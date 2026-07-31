# 13 — Orchestrate Equivalence and Generation rebuilds

**What to build:** Run explicit Batch-Incremental Equivalence and
maintenance-only result-changing Tracking Generation rebuilds as separate,
finite, durable operations without turning Temporal history into DailyTrack
product truth.

**Blocked by:** 12 — Advance DailyTrack through finite Workflows; `thesistrace-v1-research-platform/27 — Verify Batch-Incremental Equivalence over ordered Dataset Releases`.

**Status:** resolved

- [x] An authorized User can request explicit equivalence asynchronously, receive one durable P3 User Compute resource, and inspect its bounded status and canonical success or first-divergence result.
- [x] Equivalence shares the Personal Workspace limit of eight nonterminal User Compute jobs with ResearchRuns, idempotent retries do not consume another unit, and an Operator maintenance Generation rebuild is not charged as ordinary User Compute.
- [x] Equivalence follows the immutable Checkpoint chain's exact ordered Dataset Release sequence and never substitutes one latest-Release replay.
- [x] An authorized maintenance operation can create and fully execute a new Tracking Generation for a result-changing kernel fix without mutating the prior Generation.
- [x] Both operations use finite Temporal Workflows with idempotent Activities, heartbeats, cooperative cancellation, and fenced final publication.
- [x] Equivalence and Generation rebuild follow the shared resource-exhaustion policy: after at most one automatic retry, repeated exhaustion ends with stable `RESOURCE_EXHAUSTED` and publishes neither a partial verification result nor a partial Generation.
- [x] PostgreSQL remains authoritative for request, ownership, lifecycle, and published result; Workflow History contains only orchestration state and opaque control identities.
- [x] Repeating one idempotent request cannot duplicate an equivalence resource or Generation rebuild, while a deliberate rerun creates a new domain request.
- [x] Cross-Personal-Workspace identifiers and non-Operator Generation rebuild attempts receive sanitized non-disclosing denial.

## Comments

- Added durable, bounded Equivalence and maintenance Generation-rebuild
  resources, stable finite Temporal Workflows, and execution-outbox start and
  cancellation delivery. Equivalence is charged against the shared
  eight-job User Compute admission boundary; Operator rebuilds are not.
- Equivalence pins one immutable Generation and Head and verifies the exact
  ordered Dataset Release chain. Its successful result retains only a release
  count and trace-chain checksum; divergence retains only the first path.
- Generation and replay Advance creation bind to the rebuild resource in the
  same Track-locked transaction. Cancellation or terminal failure advances the
  fencing coordinate and removes every unpublished Generation, Advance, and
  Attempt; a publication that already won is reconciled to success.
- Both Activities heartbeat through bounded calculation stages, persist
  cooperative cancellation, reject late publication, and propagate nested
  Advance resource exhaustion. The second resource-exhausted execution ends
  with stable `RESOURCE_EXHAUSTED`.
- Hosted RLS and grants preserve Personal Workspace isolation and the
  Operator-only rebuild boundary. Start and cancel outbox IDs include their
  resource kinds, and missing Workflow cancel targets are treated as
  idempotently complete.
- Verification: focused Hosted/Tracking/Quota/Research regression
  (`37 passed, 1 skipped`), full backend suite (`171 passed, 11 skipped`),
  Hosted 13 focused suite after cancellation hardening (`20 passed`), Ruff,
  Web typecheck/build, package build, and two independent final reviews
  completed successfully.
