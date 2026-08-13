# 07 — Rename and move Research without changing provenance

**What to build:** Let researchers reorganize completed or in-progress Research by
changing its display name or Folder while preserving identity, immutable input,
Attempts, provenance, status, and results.

**Blocked by:** 04 — Manage custom Research Folders; 05 — Run a Formula as immutable Research

**Status:** complete

- [x] A researcher can rename Research from its list or detail experience without creating another Run.
- [x] A researcher can move Research to Default or a custom Folder without creating another Run.
- [x] Names may duplicate within or across Folders and never create a rename/move conflict.
- [x] Rename and move change only mutable organization metadata.
- [x] Immutable input bytes, checksum, compiled Expression, field bindings, Attempts, provenance, status, and result remain exactly unchanged.
- [x] Moving Research does not move, copy, restore, or overwrite any browser Draft.
- [x] Moving to a missing Folder conflicts and leaves organization metadata unchanged.
- [x] Folder-filtered lists reflect rename/move immediately and retain stable cursor behavior.
- [x] Real PostgreSQL integration tests prove metadata isolation and concurrent constraint behavior.
- [x] Frontend and browser tests prove rename/move and duplicate-name rendering end to end.

## Comments

- Research organization is deliberately independent of frozen authorable input and Draft ownership.
- Verification: Python regression passed 388 tests; Ruff passed; frontend typecheck and 20 component tests passed. Fresh PostgreSQL/RustFS integration `20260812t183242z-66118-cdd962bd` passed 112 tests plus one restart test with cleanup. Fresh production-image E2E `20260812t184417z-76041-fe98264f` passed both browser journeys with cleanup, including held-PATCH concurrency and Folder 503 recovery.
- Review: Standards and Spec reviews both passed on frozen staged SHA `932a51b07a322136fc3622f0b70a64386d195e79b31208636f9c515499f4c173` with no material findings.
