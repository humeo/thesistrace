# 03 — Author one Browser Draft in the Default Folder

**What to build:** Give a researcher a formula-first workspace backed by one
system-owned Default Folder and one browser-local Draft, with completion and diagnostics
but no server Save or Revision workflow.

**Blocked by:** 01 — Publish safe Alpha Catalog and Formula Diagnostics

**Status:** complete

- [x] A fresh product database contains exactly one deterministic Default Folder and the Folder is exposed through the public Folder read contract.
- [x] The active Research workspace opens the Default Folder from global New Research and presents the DSL editor as the only Alpha authoring surface.
- [x] CodeMirror provides field/builtin completion, documentation, and backend source-ranged diagnostics without implementing a second authoritative parser.
- [x] The browser stores exactly one bounded Draft under the Default Folder, including Formula, research parameters, editor state, and last admitted local baseline.
- [x] Absence of the local Draft key opens an empty editor and never restores the latest ResearchRun.
- [x] Browser refresh or reopen restores the same local Draft without any server Draft resource or autosave request.
- [x] New clears the Draft explicitly and confirms only when unexecuted local changes would be lost.
- [x] Debounced diagnostic requests ignore stale responses, and a preview-network failure does not mark the Formula valid.
- [x] Save, Refresh, and Revision controls are absent from the active workspace.
- [x] Real database, frontend-state, HTTP-contract, and browser tests prove the Default Folder and Draft behavior.

## Comments

- Direct Run is deliberately delivered by tickets 05 and 06; this ticket's complete observable behavior is authoring and retaining a diagnosable local Draft.
- Verification: frontend typecheck and 11 state/shell tests passed; real isolated PostgreSQL/RustFS integration passed 118 tests plus one database-restart test; fresh-stack browser run `20260812t161450z-91512-3d4eaa37` passed.
- Review: initial Standards/Spec reviews found the missing global New entry and incomplete browser proof for completion documentation/ranged diagnostics. Both were fixed. Mandatory re-review passed on frozen staged SHA `14b7a63afc5047ec25375e035c0b197f51345566fd3558c958ffbefa28a02886` with no material findings.
