# 10 — Preserve ordinary Run organization and granular deletion

**What to build:** Keep Batch-produced ResearchRuns fully usable through the
existing Research organization and detail experience, while preserving immutable
Batch history when a researcher moves, renames, reuses, tracks, or deletes one
terminal child Run.

**Blocked by:** 06 — Report truthful Batch history, outcomes, and progress

**Status:** complete

## Implementation plan

1. Keep Batch ownership anchored exclusively in immutable Batch Items while
   exercising the existing Folder and ResearchRun organization contracts for
   Batch-owned and ordinary Runs in the stable Batch Research Folder.
2. Add one narrow Batch-history deletion hook to the ordinary terminal Run
   deletion transaction so it records a terminal child's deletion timestamp
   before removing the Run and releasing any unreferenced Result publication.
3. Make Batch detail project available child status from ResearchRun state and
   deleted child status from the Batch Item's durable final outcome, without
   changing aggregate progress, outcome, ordinals, or item keys.
4. Cover rename, move, ordinary admission into Batch Research, browser Draft
   reuse, terminal-only granular deletion, sibling/Batch/history retention, and
   independent DailyTrack retention with the existing API and browser surfaces.
5. Run focused real-dependency acceptance and frontend tests plus full gates,
   resolve independent Standards/Spec review findings, and commit this ticket
   separately.

- [x] The system maintains one stable Folder with identity folder_batch_research and display name Batch Research as the default destination for newly admitted Batch child Runs.
- [x] The stable Folder supports ordinary Browser Draft and Run behavior and may contain ordinary non-Batch ResearchRuns.
- [x] Deleting the stable Folder is rejected, while its display and ordinary organizational behavior remain consistent with other Research Folders.
- [x] A Batch-owned Run can be renamed or moved to another Folder without changing its immutable Batch Item membership, ordinal, item_key, calculation identity, or history.
- [x] Folder membership is never consulted as the source of Batch ownership, execution eligibility, cancellation scope, or Batch detail membership.
- [x] Use as Draft on a Batch-owned Run creates only an ordinary Browser Draft and preserves the existing Research Kind and applicable authorable inputs.
- [x] Batch child Runs remain visible through the existing Research list and detail surfaces for queued, running, succeeded, failed, and cancelled states.
- [x] A terminal Batch-owned Run retains the existing Delete Research action and the same terminal-only deletion authorization as an ordinary Run.
- [x] Deleting one child removes that ResearchRun and its unreferenced Result objects through the ordinary Publication deletion lifecycle without deleting the Batch or sibling Runs.
- [x] Batch detail preserves the deleted child's original ResearchRun ID, final outcome, ordinal, item_key, and deletion timestamp and reports that the Run is no longer available.
- [x] Child deletion never rewrites the Batch aggregate outcome or durable completed-task history.
- [x] A DailyTrack independently activated from a successful Strategy child remains intact when its seed ResearchRun is later deleted.
- [x] No whole-Batch DELETE endpoint, cascading child cleanup action, synthetic deleted Batch outcome, or Folder-based compatibility behavior is introduced.
- [x] Existing Research browser acceptance verifies child visibility, organization, reuse, terminal deletion, sibling retention, and DailyTrack retention; no Batch-specific frontend route or controls are added.

## Comments

- Parent: Research Batch Worker.
- Batch membership is immutable orchestration history; Folder placement remains ordinary mutable organization.
- Implementation: ordinary terminal Run deletion invokes one narrow Batch-owned
  history hook in the same PostgreSQL transaction, recording `run_deleted_at`
  before the Run and any unreferenced Result publication are removed. Batch
  detail derives a deleted child's status from its durable final outcome.
- Concurrency: Batch detail locks its Item projection with `FOR SHARE`; terminal
  child deletion obtains the corresponding `FOR UPDATE`, so readers observe a
  coherent available or deleted state rather than a missing-Run race.
- Verification: Ruff, TypeScript, diff, and shell syntax passed; the final fast
  gates passed `561` Python and `57` frontend tests. Real Playwright run
  `20260824t091716z-434-8820b356` passed all `6` browser tests. Real PostgreSQL/
  RustFS run `20260824t092013z-2085-dcc3ed17` passed `235` main tests plus all
  five dependency-restart phases, and both runs finished with `status=0` and
  `cleanup_status=0`.
- Independent Standards final re-review: PASS (`P0/P1/P2 = 0/0/0`).
- Independent Spec final re-review: PASS (`P0/P1/P2 = 0/0/0`) after adding the
  real browser journey and closing the concurrent detail/delete projection race.
