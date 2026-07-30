---
status: accepted
---

# Let deleted payloads expire from disaster-recovery backups

Hosted Platform V2 keeps encrypted disaster-recovery backups outside the
single Compose node. These backups cover InsForge PostgreSQL and the matching
InsForge Storage objects as one recoverable platform state. They are restricted
to operators and exist only for whole-platform disaster recovery; Users cannot
browse them or request restoration of an individual resource.

Deleting a terminal private resource still removes its live references and
active Storage objects immediately under ADR-0118. A copy already captured by
a backup may remain inaccessible until that backup reaches its fixed expiry.
Backup retention is not an online garbage-collection delay, does not retain the
resource in product APIs, and does not count against Workspace quota.

A platform restore must reconcile retained Resource Tombstones before the
service becomes available so that disaster recovery never makes a deleted
resource readable again. Backup expiry removes the remaining payload copy
without offering a User recovery path.

The first hosted deployment creates one coordinated, encrypted off-node backup
every six hours. Each backup covers the InsForge product database, Temporal
persistence and Visibility databases, and the matching InsForge Storage
objects. Backups expire after seven days; the first release keeps no separate
weekly, monthly, or permanent archive.

The recovery-point objective is at most six hours of committed platform state.
Because ADR-0139 uses daily operator inspection instead of active alert
delivery, the first release accepts a mean-time-to-detect objective of at most
24 hours. After detection, the recovery execution objective is at most eight
hours and permits an operator to provision and restore a replacement single
node manually. The resulting worst-case end-to-end interruption objective is
approximately 32 hours rather than eight hours from failure occurrence.

A real recovery exercise must restore the PostgreSQL and Storage state,
reconcile Tombstones, and pass platform health checks before the hosted release
opens to invited Users.
