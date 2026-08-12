# 06 — Run a Draft from the browser and view results

**What to build:** Complete the primary user journey from the current Folder Draft to a
new Research status and published result, while retaining the submitted Draft locally.

**Blocked by:** 05 — Run a Formula as immutable Research

**Status:** ready-for-agent

- [ ] Run submits the exact current complete Draft and a stable request ID to direct ResearchRun admission.
- [ ] Accepted Run navigates to or reveals the new Research, follows queued/running/terminal status, and displays the published result through existing result semantics.
- [ ] Rejected Run renders backend issues at the correct Formula ranges and creates no history item.
- [ ] Run never clears or rewrites the Draft.
- [ ] The local executed baseline becomes the exact snapshot accepted by that Run; edits made while the request is pending remain unexecuted.
- [ ] Global New creates Research in Default Folder, and Run from a custom Folder creates Research in that selected Folder.
- [ ] History distinguishes duplicate names with Run ID, creation time, status, and Formula summary.
- [ ] Request retry, stale response, navigation, and error states do not create duplicate Research or lose local edits.
- [ ] The active browser journey exposes Formula and Run but no Save, Refresh, Revision, or Definition interaction.
- [ ] Real browser E2E proves Default and custom Folder `Draft -> Run -> result`, including rejection and refresh behavior with screenshots on failure.

## Comments

- Tickets 07, 08, and 09 can proceed independently after this primary browser loop is green.
