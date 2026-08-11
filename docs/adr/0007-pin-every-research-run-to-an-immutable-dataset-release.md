---
status: superseded by ADR-0151
---

# Pin every ResearchRun to an immutable Dataset Release

Every ResearchRun consumes a Research Definition containing the exact identity
of one immutable Dataset Release. An editor may initially select `latest`, but
the Run request defined by ADR-0098 freezes the definition and resolves and
records a concrete release before execution; later data publication never
changes an existing run's inputs or meaning.

The pinned release binds its Research Calendar, Universe snapshots, Canonical
Dataset Schemas and data objects, Adjustment Factors, and other required dated
families as one logical snapshot. A
ResearchRun cannot combine components from different releases.

This single-release rule remains unchanged for ResearchRun. ADR-0103 gives a
DailyTrack a separate stable identity: it pins the seed Definition semantics
without mutating that Definition, while each immutable Tracking Advance binds
its own later target Dataset Release.
