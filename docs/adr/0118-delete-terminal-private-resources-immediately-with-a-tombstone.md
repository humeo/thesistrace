---
status: accepted
---

# Delete terminal private resources immediately with a Tombstone

A Personal Workspace may delete a terminal ResearchRun or a stopped DailyTrack
as one complete resource. Queued or running ResearchRuns and active DailyTracks
cannot be deleted. A ResearchRun that remains the seed of a retained DailyTrack
cannot be deleted before that Track. Deletion never edits a Result Bundle,
Generation, or Checkpoint.

Deletion creates a permanent Resource Tombstone containing the resource
identity, authoritative manifest hash, actor, and deletion time. Deletion is
irreversible and has no recovery grace period. The platform immediately removes
the resource's references and physically deletes each private object that has no
remaining live reference. Platform-owned Dataset Releases are never
user-deletable.

If physical deletion fails, the resource remains in a non-readable `deleting`
state and cleanup retries idempotently until it succeeds. Storage quota is
released when physical deletion completes; the Tombstone itself remains.

Immediate deletion applies to the active InsForge Storage backend. ADR-0127
allows encrypted, operator-only disaster-recovery backups to retain an
inaccessible copy until the backup containing it expires. This is not a
recovery grace period, does not delay quota release, and never permits
per-resource or User-requested restoration.
