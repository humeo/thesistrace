# 21 — Back up and restore the coordinated platform

**What to build:** Create encrypted off-node backups that coordinate product
metadata, Temporal execution state, and matching immutable objects, then prove
a restored node reconciles deletions and health before reopening the public
Origin.

**Blocked by:** 17 — Delete terminal resources through Tombstones; 20 — Release through migrations, maintenance, and rollback.

**Status:** ready-for-agent

- [ ] A scheduled operation creates one coordinated encrypted off-node backup at least every six hours and expires backup material after seven days.
- [ ] Each recovery set contains the matching product PostgreSQL state, Temporal persistence and Visibility state, immutable Storage objects, version metadata, and separately protected secret recovery material.
- [ ] Backup failure is visible to the Operator without blocking unrelated API readiness or publishing an incomplete recovery set as successful.
- [ ] A full restore keeps the public Origin closed while it reconciles Resource Tombstones, removes logically deleted payload access, verifies object indexes, and passes platform health checks.
- [ ] Payloads present only in unexpired disaster-recovery backups never become User-accessible after restoration.
- [ ] A real recovery exercise records evidence for no more than six hours of committed-state loss, the documented daily-inspection detection window, and execution of recovery within the launch objective.
- [ ] The restored system preserves Personal Workspace isolation, authoritative resource state, Workflow recovery, and the latest valid Dataset Release.
