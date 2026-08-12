# 04 — Manage custom Research Folders

**What to build:** Let researchers create simple one-level Folders and keep one
independent browser Draft in each Folder without introducing a durable Research or Draft
container.

**Blocked by:** 03 — Author one Browser Draft in the Default Folder

**Status:** ready-for-agent

- [ ] A researcher can create a custom Folder with a nonblank user-chosen name and see it immediately in Folder navigation.
- [ ] A researcher can rename a custom Folder without changing any Draft or Research input.
- [ ] A researcher can delete an empty custom Folder explicitly.
- [ ] Deleting the Default Folder or a nonempty custom Folder returns a conflict and neither moves nor deletes Research.
- [ ] Folders cannot nest and expose no Formula, parameters, Draft, Revision, or execution state on the server.
- [ ] Every Folder uses a distinct browser-local Draft key; switching Folders restores the matching Draft only.
- [ ] New Research inside a selected custom Folder targets that Folder, while global New Research still targets Default.
- [ ] Clearing or overwriting one Folder's Draft never mutates another Folder's Draft.
- [ ] Folder create/rename/delete constraints are enforced transactionally in a real isolated PostgreSQL database.
- [ ] Frontend and browser tests cover navigation, per-Folder Draft persistence, destructive confirmation, and Folder deletion conflicts.

## Comments

- Folder management is independent of direct Run and can proceed while tickets 02 and 05 develop the execution path.
