# 04 — Manage custom Research Folders

**What to build:** Let researchers create simple one-level Folders and keep one
independent browser Draft in each Folder without introducing a durable Research or Draft
container.

**Blocked by:** 03 — Author one Browser Draft in the Default Folder

**Status:** complete

- [x] A researcher can create a custom Folder with a nonblank user-chosen name and see it immediately in Folder navigation.
- [x] A researcher can rename a custom Folder without changing any Draft or Research input.
- [x] A researcher can delete an empty custom Folder explicitly.
- [x] Deleting the Default Folder or a nonempty custom Folder returns a conflict and neither moves nor deletes Research.
- [x] Folders cannot nest and expose no Formula, parameters, Draft, Revision, or execution state on the server.
- [x] Every Folder uses a distinct browser-local Draft key; switching Folders restores the matching Draft only.
- [x] New Research inside a selected custom Folder targets that Folder, while global New Research still targets Default.
- [x] Clearing or overwriting one Folder's Draft never mutates another Folder's Draft.
- [x] Folder create/rename/delete constraints are enforced transactionally in a real isolated PostgreSQL database.
- [x] Frontend and browser tests cover navigation, per-Folder Draft persistence, destructive confirmation, and Folder deletion conflicts.

## Comments

- Folder management is independent of direct Run and can proceed while tickets 02 and 05 develop the execution path.
- Verification: Python regression passed 377 tests; frontend typecheck and 13 state/shell tests passed; real isolated PostgreSQL/RustFS integration run `20260812t162958z-584-d4ddaa29` passed 119 tests plus one database-restart test; fresh-stack production-image browser run `20260812t163724z-3633-b10e60fc` passed and cleaned its isolated environment.
- Review: Standards and Spec reviews both passed on frozen staged SHA `3278a39a998eca78f6bec91e80f19888c8393333fb550fe7d0b21feda5861763` with no material findings.
