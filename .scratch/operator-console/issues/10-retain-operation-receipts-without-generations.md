# 10 — Retain operation receipts without retaining Data Generations

**What to build:** Keep enough recent Data Refresh history for the Operator to
understand operational outcomes while ensuring that receipt retention cannot
silently become a Dataset Generation retention policy.

**Blocked by:** 08 — Cancel accepted work and Retry immutably; 09 — Recover Worker
claims and surface availability.

**Status:** complete

- [x] Non-terminal operation receipts are never removed by retention cleanup.
- [x] Terminal published, no-change, degraded, failed, cancelled, and
  retry-exhausted receipts remain queryable for 180 days and become eligible for
  deterministic cleanup afterward.
- [x] Cleanup preserves stable pagination and latest-operation-per-kind semantics
  for every receipt that remains visible.
- [x] A receipt does not retain a Data Generation, add a Garbage Collection root,
  or prevent collection of otherwise unreachable Canonical or raw evidence.
- [x] Removing an old receipt never changes the current Dataset Head, readiness,
  or a newer operation's state.
- [x] Cleanup is idempotent, bounded, observable through safe counts, and does not
  expose deleted receipt contents or storage paths.
- [x] Fixed-clock integration tests with real PostgreSQL and RustFS cover the
  180-day boundary, every terminal state, preservation of non-terminal work,
  repeated cleanup, pagination, and Generation collection.
- [x] The Console handles a history page changing after cleanup without duplicate
  rows, broken cursors, or misleading empty state.

## Implementation Plan

1. Extend the existing private Data Garbage Collection fixed plan rather than
   adding a second scheduler or public endpoint. On creation of a new collection
   plan, select only `succeeded`, `failed`, or `cancelled` Refresh receipts whose
   `finished_at` is strictly older than the 180-day boundary, ordered by
   `finished_at` and idempotency key, with a hard per-run limit. Keep the selected
   cutoff fixed for the operation and never select `accepted` or `running` rows.
2. Delete the selected receipts atomically with creation of the collection plan,
   include their identities only in the plan hash, and persist only a bounded
   deleted-receipt count. Reusing the same collection idempotency key must return
   the same count and never widen the receipt or file plan; a new key may process
   the next deterministic batch. Add the current-schema column and retention
   index directly, with no migration, compatibility, or alternate cleanup path.
3. Preserve the existing Data Lifecycle root contract exactly: current Head,
   active Generation Pins, live candidates, and explicit Financial/Industry raw
   retention remain the only roots. Do not consult Refresh receipt generation
   fields while planning file deletion, and prove that a still-retained receipt
   cannot keep an otherwise unreachable Canonical Generation or raw Financial
   evidence alive.
4. Keep Dataset Operational Status keyset pagination based on immutable
   `created_at` plus idempotency key and verify the same cursor remains valid
   when eligible older rows disappear. Update Console copy to state the 180-day
   terminal retention policy and distinguish an emptied older page from a
   never-used history, preserving the existing Newer navigation without adding
   duplicate rows or a fallback cursor.
5. Add fixed-clock, real-PostgreSQL integration coverage for every terminal
   outcome, the exact 180-day boundary, accepted/running preservation, stable
   batch order and limit, same-key idempotency, safe counts, latest-per-kind,
   pagination after deletion, unchanged Head/readiness, and Generation/raw-file
   collection. Add focused schema, CLI outcome, and Web rendering tests at the
   lowest existing seams.
6. Run narrow tests, the full host gate, real dependency integration, real Caddy
   E2E when browser behavior changes, and Production Image Smoke. Review the
   Ticket 10 diff for Standards and Spec independently, fix every finding,
   re-review, mark this issue complete, and commit Ticket 10 as its own
   acceptance unit.

## Verification

- Focused real-dependency run `20260830t143909z-56454-11cf9e38`: all five
  selected Ticket 10 tests passed against a fresh PostgreSQL/RustFS runtime,
  covering the strict 180-day boundary, all terminal receipt meanings,
  accepted/running preservation, a three-receipt batch limit, same-key replay,
  failed file-plan recovery without receipt-plan widening, deletion of the row
  encoded by a still-valid keyset cursor, safe CLI counts, and collection of
  Canonical/raw Financial evidence despite a retained receipt.
- Final host gate passed Ruff and both typechecks with 928 Python tests, 171 Auth
  tests, and 148 Web tests. The only warning was the existing local-lifecycle
  `forkpty()` deprecation warning.
- Final real-dependency run `20260830t145356z-72206-f6ffdf87`: 416 primary
  PostgreSQL/RustFS tests passed with eight marker-selected tests deferred, then
  the database-restart phase and all five independent RustFS/PostgreSQL recovery
  phases passed. The first full run had two unrelated DailyTrack activation 409s;
  both passed together in a fresh focused run and the final complete run did not
  reproduce them. Every isolated container, network, and mutable volume was
  removed.
- Real Caddy browser run `20260830t144528z-67685-4a7d5c9f`: 16/16 tests passed in
  5.4 minutes, including the singleton Operator boundary, all three Refresh
  kinds, Worker recovery, operation details, and visible 180-day terminal
  receipt policy. Runtime-secret cleanup, Compose cleanup, and the overall run
  all reported status zero.
- Production Image Smoke run `20260830t151639z-92216-0778b7b0`: every Core/Web
  phase reported status zero, including current-schema empty-volume startup,
  secret scope, long execution, Worker loss, PostgreSQL/RustFS restart,
  persistence, product-state reset, bounded evidence, and MCP HTTP/stdio.
  Runtime-secret cleanup, Compose cleanup, and the overall run reported status
  zero; the independent Auth and Caddy image smokes also passed.
- Standards review fixed strict integer validation for the bounded batch size,
  avoided consulting the clock when replaying an existing fixed plan, preserved
  exact fixed-plan behavior after file deletion failure, and removed incidental
  formatter churn. Re-review found no remaining transaction, idempotency,
  privacy, lifecycle-root, pagination, accessibility, or current-schema finding.
- Spec review: PASS. Terminal receipts are selected strictly by `finished_at <`
  the fixed cutoff and stable identity order, their identities exist only in the
  plan hash, only a safe count persists, non-terminal receipts are excluded,
  retained receipts never become Generation roots, and the Console remains
  truthful and navigable when cleanup changes an older page.
