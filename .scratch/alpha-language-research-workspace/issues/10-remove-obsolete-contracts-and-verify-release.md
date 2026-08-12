# 10 — Remove obsolete contracts and verify the release

**What to build:** Finish the hard cut by deleting every obsolete Definition, Revision,
Save, Refresh, and Rerun contract, align domain documentation, and prove the already
green feature through the final production-image and real-browser release gates.

**Blocked by:** 04 — Manage custom Research Folders; 07 — Rename and move Research without changing provenance; 08 — Reuse Research only through Use as Draft; 09 — Delete Research and DailyTracks independently

**Status:** complete

- [x] No active or dead backend route, runtime composition, schema object, model, receipt, ancestry field, frontend route/control/link, or test retains the server Definition/Revision or product Rerun lifecycle.
- [x] Architecture checks fail if a duplicate field allowlist, physical Kernel field map, Worker Formula compilation, Python execution primitive, compatibility endpoint, dual schema, migration, fallback parser, or old/new switch is reintroduced.
- [x] Domain glossary and ADR status accurately describe Formula, Alpha Expression, Browser Draft, Research Folder, ResearchRun, Attempt, Use as Draft, and independent deletion, and superseded ADR clauses remain historically traceable.
- [x] The final calibrated Formula work limits and performance-regression benchmark pass on their fixed representative dataset.
- [x] Focused checks from every preceding ticket are green before the final gate begins; this ticket does not hide unrelated defect discovery inside one acceptance loop.
- [x] Static checks, deterministic unit/architecture/data tests, frontend typecheck, and shell tests pass.
- [x] Real isolated PostgreSQL, Worker, object-storage, idempotency, retry, cancellation, publication, Folder, deletion, and DailyTrack integration tests pass from a fresh database.
- [x] Full browser E2E passes for Catalog/Diagnostics, Default/custom Folder Drafts, Run/result, rename/move, Use as Draft, Research deletion, Track survival, Stop, and Track deletion.
- [x] Final production images start on a fresh isolated stack, become ready, expose only the new HTTP contract, execute Run to result, and complete Track start/stop/delete smoke.
- [x] Real in-app-browser acceptance confirms the visible workflow contains no Save, Refresh, Revision, Rerun, or Definitions UI and retains diagnostic screenshots/logs on failure.
- [x] The complete release gate passes without public-network dependency, arbitrary sleep, retry-to-green behavior, or unrecorded manual repair.

## Comments

- Final acceptance orchestrates already-green gates. A material failure reopens the responsible slice or creates an explicit focused fix instead of expanding this ticket into a debugging epic.
- Fixed implementation review SHA: `d1dd264ec4d263fe6335c88023975bfcefa416e42e89090f69ab3bf064d38361`; Standards and Spec both passed.
- One complete `bun run check:release` passed: local 380 backend and 25 frontend tests; isolated integration run `20260812t194749z-10972-e047ad09` passed 117/117 plus database restart 1/1; E2E run `20260812t194915z-11437-21f52e54` passed 2/2; production-image smoke `20260812t195001z-11720-c9c8a87e` passed every phase. All isolated runs recorded cleanup 0.
- Real in-app-browser acceptance inspected Data, Research, Research Runs, and Daily Tracks, found no obsolete authoring controls, observed one source-ranged `UNKNOWN_IDENTIFIER` diagnostic for `unknown_field`, cleared the test Draft, and observed no console errors.
