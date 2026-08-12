# 08 — Reuse Research only through Use as Draft

**What to build:** Replace product-level Rerun with one explicit browser action that
copies historical authorable input into the selected Folder Draft and lets the user
inspect or edit it before ordinary Run.

**Blocked by:** 06 — Run a Draft from the browser and view results

**Status:** ready-for-agent

- [ ] Research detail exposes Use as Draft for historical Research in every terminal state whose frozen authorable input is available.
- [ ] Use as Draft copies Formula, Hypothesis, requested dates, Universe, neutralization, and Strategy parameters into the selected Folder's local Draft.
- [ ] Use as Draft does not copy mutable Research name or Folder membership and creates no server resource, receipt, Attempt, or execution.
- [ ] The action confirms only when it would overwrite unexecuted local changes.
- [ ] After copying, the user may edit or Run unchanged; either path uses ordinary authoritative admission and creates a new independent ResearchRun.
- [ ] The source Research, its immutable input, result, and organization metadata remain unchanged.
- [ ] No UI action is labelled Rerun, and no product rerun endpoint, command, receipt, ancestry field, or `rerun_of` projection remains.
- [ ] Infrastructure retry remains an Attempt under the original ResearchRun and is not presented as research reuse.
- [ ] Frontend tests cover confirmation, exact copied values, target-Folder isolation, and absence of implicit Run creation.
- [ ] Real browser E2E proves `Use as Draft -> inspect/edit -> Run -> new Research` and proves the original Research remains intact.

## Comments

- This ticket owns the complete product-reuse contract; no compatibility Rerun action is retained.
