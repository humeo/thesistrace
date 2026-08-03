---
status: superseded by ADR-0151
---

# Let deleted payloads expire from disaster-recovery backups

Hosted Platform V2 creates coordinated encrypted off-node backups of PostgreSQL, Temporal state, and matching Storage objects every six hours and expires them after seven days for whole-platform disaster recovery only. Deleted payloads may remain inaccessible until backup expiry, but every restore reconciles Resource Tombstones before service so disaster recovery cannot revive deleted Personal Workspace resources.
