# 21 — Back up and restore the coordinated platform

**What to build:** Create encrypted off-node backups that coordinate product
metadata, Temporal execution state, and matching immutable objects, then prove
a restored node reconciles deletions and health before reopening the public
Origin.

**Blocked by:** 17 — Delete terminal resources through Tombstones; 20 — Release through migrations, maintenance, and rollback.

**Status:** resolved

- [x] A scheduled operation creates one coordinated encrypted off-node backup at least every six hours and expires backup material after seven days.
- [x] Each recovery set contains the matching product PostgreSQL state, Temporal persistence and Visibility state, immutable Storage objects, version metadata, and separately protected secret recovery material.
- [x] Backup failure is visible to the Operator without blocking unrelated API readiness or publishing an incomplete recovery set as successful.
- [x] A full restore keeps the public Origin closed while it reconciles Resource Tombstones, removes logically deleted payload access, verifies object indexes, and passes platform health checks.
- [x] Payloads present only in unexpired disaster-recovery backups never become User-accessible after restoration.
- [x] A real recovery exercise records evidence for no more than six hours of committed-state loss, the documented daily-inspection detection window, and execution of recovery within the launch objective.
- [x] The restored system preserves Personal Workspace isolation, authoritative resource state, Workflow recovery, and the latest valid Dataset Release.

## Comments

- Added streaming AES-GCM encrypted recovery sets with Scrypt-derived keys,
  atomic complete manifests, SHA-256 verification, seven-day complete-set
  retention, separately encrypted secret recovery, and a required initialized
  absolute off-node target outside both the repository and Hosted state.
- Added a six-hour systemd schedule and bounded operator-only backup/restore
  containers. Cold backup stops all state writers; restore authenticates the
  complete artifact before erasing mounted targets, clears disposable Working
  Cache, restores immutable Release configuration modes on the host, and opens
  Edge only after database, Tombstone, RLS, object-index, Dataset pointer, and
  public smoke gates pass.
- System Health reports the latest attempt and backup age, while API readiness
  remains independent. Unit coverage proves failed attempts preserve the prior
  successful recovery set, incomplete sets cannot be successful, wrong keys do
  not erase live volumes, and backup-only unreferenced payload bytes are not
  exposed through the authoritative object index.
- The final real exercise used recovery set
  `backup_20260801T003141Z_e7e5ea1c05d9`, restored Release Bundle
  `0.1.0-14b6c6be7ead376d`, and preserved latest Dataset Release
  `dsr_5c5940e719ac9cae9732`. The recovered Temporal Workflow
  `recovery-probe-h21-audit-20260801T002952Z` remained running and completed
  only after the release-bundled probe received its continuation signal.
  Recorded evidence passed with a 97-second committed-state-loss bound,
  zero-second simulated detection, 172 seconds of recovery execution, both
  internal recovery health gates available before reopening Edge, and a
  successful public-Origin smoke.
- The strict gate exposed a previously hidden Hosted health defect: Compute
  Workers did not update the product Worker heartbeat and the old smoke check
  accepted `degraded`. Compute Workers now publish that heartbeat every two
  seconds, smoke accepts only `available`, and the regression test plus the
  original private health repro both pass.
- Every recovery mutation now stages a sanitized host-side audit-outbox event
  before changing state, retains it across database failures, and flushes it
  idempotently only after PostgreSQL accepts the event. The final exercise
  recorded the successful restore and left the outbox empty.
