# 17 — Delete terminal resources through Tombstones

**What to build:** Let a User irreversibly delete one complete terminal private
resource, make it unreadable immediately, and reconcile physical cleanup and
quota release through a permanent minimal Resource Tombstone.

**Blocked by:** 11 — Activate and stop a quota-bound DailyTrack; 16 — Enforce private storage and disk admission; `thesistrace-bounded-research-storage/09 — Reconcile Working Cache deletion after DailyTrack stop`.

**Status:** resolved

- [x] Web and API permit deletion only for terminal ResearchRuns and stopped DailyTracks in the caller's Personal Workspace.
- [x] A ResearchRun referenced by a retained DailyTrack and any nonterminal resource are rejected without mutating their lifecycle or artifacts.
- [x] One atomic control transaction removes live product references, makes the resource immediately unreadable, and creates a permanent minimal Tombstone with identity, authoritative manifest hash, actor, and deletion time.
- [x] Object cleanup is reference-aware and idempotent, so shared bytes remain while any live resource still references them.
- [x] Private-storage quota is released only after the physical bytes and stopped Track Working Cache namespace are actually removed.
- [x] A crash after the deletion or stop commit but before cleanup is recovered by durable cleanup work and scheduled or startup reconciliation.
- [x] Another Personal Workspace cannot delete or inspect the resource or its Tombstone, and ordinary Users receive no restore or soft-delete surface.

## Resolution

- Added immutable control-plane Resource Tombstones and durable cleanup jobs.
  Deletion validates terminal state and retained dependencies, moves exact
  storage references to the Tombstone, removes the complete live product graph,
  and makes the resource unreadable in one transaction.
- Added API-only, publication-lock-serialized object deletion plus a startup and
  immediate reconciler. One cross-process storage-mutation fence serializes the
  candidate check, physical deletion, accounting commit, and concurrent
  publication. It removes a stopped Track's Working Cache first, deletes only
  objects without another live/platform reference, and releases accounting
  references only after physical cleanup succeeds.
- Refused deletion for pre-index resources until storage reconciliation has
  established their exact object references, preventing upgrade-era artifact
  leaks rather than guessing what to remove.
- Indexed local Dataset Release objects as platform references in the same
  fenced transaction as the Release commit, so deleting a Run cannot remove a
  digest still retained by an immutable Dataset Release.
- Added irreversible Web actions for terminal ResearchRuns and stopped
  DailyTracks; ordinary product APIs expose no Tombstone read or restore route.
- Verification: Ruff passed; the full suite passed with 228 tests and 14
  environment-dependent skips, including deterministic publication/cleanup,
  concurrent cleanup, and Dataset/Run shared-digest coverage; Web typecheck and
  production build passed. A fresh isolated PostgreSQL 15 database applied all
  16 migrations and proved indexed ResearchRun deletion, Tombstone reference
  transfer, and refusal to delete an unindexed pre-upgrade Run. Independent
  specification and standards reviews both passed.
