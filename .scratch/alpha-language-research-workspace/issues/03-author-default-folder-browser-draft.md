# 03 — Author one Browser Draft in the Default Folder

**What to build:** Give a researcher a formula-first workspace backed by one
system-owned Default Folder and one browser-local Draft, with completion and diagnostics
but no server Save or Revision workflow.

**Blocked by:** 01 — Publish safe Alpha Catalog and Formula Diagnostics

**Status:** ready-for-agent

- [ ] A fresh product database contains exactly one deterministic Default Folder and the Folder is exposed through the public Folder read contract.
- [ ] The active Research workspace opens the Default Folder from global New Research and presents the DSL editor as the only Alpha authoring surface.
- [ ] CodeMirror provides field/builtin completion, documentation, and backend source-ranged diagnostics without implementing a second authoritative parser.
- [ ] The browser stores exactly one bounded Draft under the Default Folder, including Formula, research parameters, editor state, and last admitted local baseline.
- [ ] Absence of the local Draft key opens an empty editor and never restores the latest ResearchRun.
- [ ] Browser refresh or reopen restores the same local Draft without any server Draft resource or autosave request.
- [ ] New clears the Draft explicitly and confirms only when unexecuted local changes would be lost.
- [ ] Debounced diagnostic requests ignore stale responses, and a preview-network failure does not mark the Formula valid.
- [ ] Save, Refresh, and Revision controls are absent from the active workspace.
- [ ] Real database, frontend-state, HTTP-contract, and browser tests prove the Default Folder and Draft behavior.

## Comments

- Direct Run is deliberately delivered by tickets 05 and 06; this ticket's complete observable behavior is authoring and retaining a diagnosable local Draft.
