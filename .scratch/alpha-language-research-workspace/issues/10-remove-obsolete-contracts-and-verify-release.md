# 10 — Remove obsolete contracts and verify the release

**What to build:** Finish the hard cut by deleting every obsolete Definition, Revision,
Save, Refresh, and Rerun contract, align domain documentation, and prove the already
green feature through the final production-image and real-browser release gates.

**Blocked by:** 04 — Manage custom Research Folders; 07 — Rename and move Research without changing provenance; 08 — Reuse Research only through Use as Draft; 09 — Delete Research and DailyTracks independently

**Status:** ready-for-agent

- [ ] No active or dead backend route, runtime composition, schema object, model, receipt, ancestry field, frontend route/control/link, or test retains the server Definition/Revision or product Rerun lifecycle.
- [ ] Architecture checks fail if a duplicate field allowlist, physical Kernel field map, Worker Formula compilation, Python execution primitive, compatibility endpoint, dual schema, migration, fallback parser, or old/new switch is reintroduced.
- [ ] Domain glossary and ADR status accurately describe Formula, Alpha Expression, Browser Draft, Research Folder, ResearchRun, Attempt, Use as Draft, and independent deletion, and superseded ADR clauses remain historically traceable.
- [ ] The final calibrated Formula work limits and performance-regression benchmark pass on their fixed representative dataset.
- [ ] Focused checks from every preceding ticket are green before the final gate begins; this ticket does not hide unrelated defect discovery inside one acceptance loop.
- [ ] Static checks, deterministic unit/architecture/data tests, frontend typecheck, and shell tests pass.
- [ ] Real isolated PostgreSQL, Worker, object-storage, idempotency, retry, cancellation, publication, Folder, deletion, and DailyTrack integration tests pass from a fresh database.
- [ ] Full browser E2E passes for Catalog/Diagnostics, Default/custom Folder Drafts, Run/result, rename/move, Use as Draft, Research deletion, Track survival, Stop, and Track deletion.
- [ ] Final production images start on a fresh isolated stack, become ready, expose only the new HTTP contract, execute Run to result, and complete Track start/stop/delete smoke.
- [ ] Real in-app-browser acceptance confirms the visible workflow contains no Save, Refresh, Revision, Rerun, or Definitions UI and retains diagnostic screenshots/logs on failure.
- [ ] The complete release gate passes without public-network dependency, arbitrary sleep, retry-to-green behavior, or unrecorded manual repair.

## Comments

- Final acceptance orchestrates already-green gates. A material failure reopens the responsible slice or creates an explicit focused fix instead of expanding this ticket into a debugging epic.
