# 06 — Run a Draft from the browser and view results

**What to build:** Complete the primary user journey from the current Folder Draft to a
new Research status and published result, while retaining the submitted Draft locally.

**Blocked by:** 05 — Run a Formula as immutable Research

**Status:** complete

- [x] Run submits the exact current complete Draft and a stable request ID to direct ResearchRun admission.
- [x] Accepted Run navigates to or reveals the new Research, follows queued/running/terminal status, and displays the published result through existing result semantics.
- [x] Rejected Run renders backend issues at the correct Formula ranges and creates no history item.
- [x] Run never clears or rewrites the Draft.
- [x] The local executed baseline becomes the exact snapshot accepted by that Run; edits made while the request is pending remain unexecuted.
- [x] Global New creates Research in Default Folder, and Run from a custom Folder creates Research in that selected Folder.
- [x] History distinguishes duplicate names with Run ID, creation time, status, and Formula summary.
- [x] Request retry, stale response, navigation, and error states do not create duplicate Research or lose local edits.
- [x] The active browser journey exposes Formula and Run but no Save, Refresh, Revision, or Definition interaction.
- [x] Real browser E2E proves Default and custom Folder `Draft -> Run -> result`, including rejection and refresh behavior with screenshots on failure.

## Comments

- Tickets 07, 08, and 09 can proceed independently after this primary browser loop is green.
- Verification: Python regression passed 388 tests; ruff passed; frontend typecheck and 18 component tests passed. Fresh production-image E2E `20260812t182141z-57846-5e56cb16` passed 2 browser journeys with cleanup. Fresh PostgreSQL/RustFS integration `20260812t181400z-53656-43db692f` passed 110 tests plus one database-restart test with cleanup.
- Review: Standards and Spec reviews both passed on frozen staged SHA `ef3126a1c2a65c04c17f1ca52014a7c769a2d46dbde9c5647893fc579e6a833f` with no material findings.
