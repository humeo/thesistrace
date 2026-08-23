---
status: accepted
---

# Organize Runs in one-level Research Folders

A user-named, one-level Research Folder exists only to organize ResearchRuns:
every Run belongs to exactly one Folder, may move without changing immutable
input or Result, and prevents deletion of its Folder while present. Folders do
not nest or own Formula, parameters, execution state, or results; one
system-owned Default Folder receives Research created from the global action.

Authoring state is exactly one browser-local Browser Draft per Folder. `New`
clears it and `Create draft` copies a selected ResearchRun's authorable values
into it, with confirmation when either would overwrite unexecuted changes;
neither action creates a backend resource. Run performs authoritative
compilation and admission, creates no durable resource on rejection, atomically
creates one ResearchRun on acceptance, and leaves the Browser Draft intact.

The product has no server-saved Research Definition, visible Revision, Save,
Refresh, or Rerun lifecycle. Keeping organization, mutable authoring state, and
immutable execution history separate avoids a durable intermediate resource
whose meaning would overlap both Browser Draft and ResearchRun.
