# 07 — Rename and move Research without changing provenance

**What to build:** Let researchers reorganize completed or in-progress Research by
changing its display name or Folder while preserving identity, immutable input,
Attempts, provenance, status, and results.

**Blocked by:** 04 — Manage custom Research Folders; 05 — Run a Formula as immutable Research

**Status:** ready-for-agent

- [ ] A researcher can rename Research from its list or detail experience without creating another Run.
- [ ] A researcher can move Research to Default or a custom Folder without creating another Run.
- [ ] Names may duplicate within or across Folders and never create a rename/move conflict.
- [ ] Rename and move change only mutable organization metadata.
- [ ] Immutable input bytes, checksum, compiled Expression, field bindings, Attempts, provenance, status, and result remain exactly unchanged.
- [ ] Moving Research does not move, copy, restore, or overwrite any browser Draft.
- [ ] Moving to a missing Folder conflicts and leaves organization metadata unchanged.
- [ ] Folder-filtered lists reflect rename/move immediately and retain stable cursor behavior.
- [ ] Real PostgreSQL integration tests prove metadata isolation and concurrent constraint behavior.
- [ ] Frontend and browser tests prove rename/move and duplicate-name rendering end to end.

## Comments

- Research organization is deliberately independent of frozen authorable input and Draft ownership.
