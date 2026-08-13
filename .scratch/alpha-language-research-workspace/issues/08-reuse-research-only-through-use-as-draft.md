# 08 — Reuse Research only through Use as Draft

**What to build:** Replace product-level Rerun with one explicit browser action that
copies historical authorable input into the selected Folder Draft and lets the user
inspect or edit it before ordinary Run.

**Blocked by:** 06 — Run a Draft from the browser and view results

**Status:** complete

- [x] Research detail exposes Use as Draft for historical Research in every terminal state whose frozen authorable input is available.
- [x] Use as Draft copies Formula, Hypothesis, requested dates, Universe, neutralization, and Strategy parameters into the selected Folder's local Draft.
- [x] Use as Draft does not copy mutable Research name or Folder membership and creates no server resource, receipt, Attempt, or execution.
- [x] The action confirms only when it would overwrite unexecuted local changes.
- [x] After copying, the user may edit or Run unchanged; either path uses ordinary authoritative admission and creates a new independent ResearchRun.
- [x] The source Research, its immutable input, result, and organization metadata remain unchanged.
- [x] No UI action is labelled Rerun, and no product rerun endpoint, command, receipt, ancestry field, or `rerun_of` projection remains.
- [x] Infrastructure retry remains an Attempt under the original ResearchRun and is not presented as research reuse.
- [x] Frontend tests cover confirmation, exact copied values, target-Folder isolation, and absence of implicit Run creation.
- [x] Real browser E2E proves `Use as Draft -> inspect/edit -> Run -> new Research` and proves the original Research remains intact.

## Comments

- This ticket owns the complete product-reuse contract; no compatibility Rerun action is retained.
- Verification: frontend typecheck and 24 component tests passed. Fresh production-image E2E `20260812t185258z-80086-24e3ba8d` passed both browser journeys with cleanup and proved local copy, inspection/editing, ordinary admission, independent Research identity, and unchanged source detail.
- Review: Standards and Spec reviews both passed on frozen staged SHA `7be52f49b10cc6d23cdcebf0aa1df168af291a04de7e6f01edc5f14188d5d624` with no material findings.
