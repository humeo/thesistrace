# 10 — Preserve ordinary Run organization and granular deletion

**What to build:** Keep Batch-produced ResearchRuns fully usable through the
existing Research organization and detail experience, while preserving immutable
Batch history when a researcher moves, renames, reuses, tracks, or deletes one
terminal child Run.

**Blocked by:** 06 — Report truthful Batch history, outcomes, and progress

**Status:** ready-for-agent

- [ ] The system maintains one stable Folder with identity folder_batch_research and display name Batch Research as the default destination for newly admitted Batch child Runs.
- [ ] The stable Folder supports ordinary Browser Draft and Run behavior and may contain ordinary non-Batch ResearchRuns.
- [ ] Deleting the stable Folder is rejected, while its display and ordinary organizational behavior remain consistent with other Research Folders.
- [ ] A Batch-owned Run can be renamed or moved to another Folder without changing its immutable Batch Item membership, ordinal, item_key, calculation identity, or history.
- [ ] Folder membership is never consulted as the source of Batch ownership, execution eligibility, cancellation scope, or Batch detail membership.
- [ ] Use as Draft on a Batch-owned Run creates only an ordinary Browser Draft and preserves the existing Research Kind and applicable authorable inputs.
- [ ] Batch child Runs remain visible through the existing Research list and detail surfaces for queued, running, succeeded, failed, and cancelled states.
- [ ] A terminal Batch-owned Run retains the existing Delete Research action and the same terminal-only deletion authorization as an ordinary Run.
- [ ] Deleting one child removes that ResearchRun and its unreferenced Result objects through the ordinary Publication deletion lifecycle without deleting the Batch or sibling Runs.
- [ ] Batch detail preserves the deleted child's original ResearchRun ID, final outcome, ordinal, item_key, and deletion timestamp and reports that the Run is no longer available.
- [ ] Child deletion never rewrites the Batch aggregate outcome or durable completed-task history.
- [ ] A DailyTrack independently activated from a successful Strategy child remains intact when its seed ResearchRun is later deleted.
- [ ] No whole-Batch DELETE endpoint, cascading child cleanup action, synthetic deleted Batch outcome, or Folder-based compatibility behavior is introduced.
- [ ] Existing Research browser acceptance verifies child visibility, organization, reuse, terminal deletion, sibling retention, and DailyTrack retention; no Batch-specific frontend route or controls are added.

## Comments

- Parent: Research Batch Worker.
- Batch membership is immutable orchestration history; Folder placement remains ordinary mutable organization.
