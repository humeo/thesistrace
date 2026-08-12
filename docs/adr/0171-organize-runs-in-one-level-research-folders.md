---
status: accepted
---

# Organize Runs in one-level Research Folders

ThesisTrace replaces the server-saved Research Definition and visible Revision
workflow with a user-named, one-level Research Folder that exists only to
organize ResearchRuns. Every ResearchRun belongs to exactly one Folder, may be
moved without changing its immutable input or results, and remains the durable
history of a user-requested research event. A Folder stores no Formula,
research parameter, Revision, execution state, or Draft; it cannot be nested,
and it cannot be deleted while it contains Runs. One system-owned Default
Folder cannot be deleted and receives Research created from the global New
action; users may create additional Folders and start Research directly inside
them.

Authoring state is exactly one Browser Draft per Folder, persisted only in that
browser through localStorage or IndexedDB, and includes Formula, Hypothesis,
Requested Research Dates, Universe, neutralization, Strategy parameters, and
editor state. It has no server identity or audit authority. When no local Draft
exists, the editor starts empty and never loads the most recent Run implicitly;
`Use as Draft` is the only action that copies a selected Run's frozen input over
the current Draft, while `New` explicitly clears it. Either destructive action
requires confirmation when unexecuted local changes exist. Run submits the
Draft for authoritative compilation and admission, creates no durable backend
resource on rejection, atomically creates one ResearchRun with its full input
snapshot on acceptance, and leaves the Draft intact. The ordinary authoring
flow therefore exposes Run but no Save, Refresh, or Revision control.

The frontend calls each ResearchRun a Research. An optional prospective name is
part of the Browser Draft, and successful admission creates the resource
directly inside the selected Folder, or inside the Default Folder when the user
started from the global action. A blank name receives a generated default.
There is no intermediate durable Research or Definition container between
Folder and ResearchRun.

This decision supersedes the Research Definition authoring lifecycle described
by ADR-0151 and every older reference to a frozen Research Definition. Those
references now mean the immutable ResearchRun input snapshot; the existing
ResearchRun Attempt, Dataset Head selection, result publication, and DailyTrack
invariants remain unchanged.

If cross-device Draft continuity later becomes a product requirement,
ThesisTrace may introduce a separate server Draft Resource at that time; the
current Folder and ResearchRun contracts do not pre-model synchronization.
