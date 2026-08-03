Status: ready-for-agent

# ThesisTrace Core Closure

## Problem Statement

ThesisTrace already contains substantial quantitative, storage, tracking, and
Hosted V2 work, but the active implementation does not close the current
product loop cleanly. Product rules are spread across large HTTP, persistence,
tracking, and Web files; Core imports Hosted code; Local and Hosted assembly
paths coexist; Draft, Frozen Version, Attempt, Advance, Checkpoint, raw objects,
and deployment mechanics leak into the product surface. The default check also
mixes Core and Hosted acceptance.

The current development phase does not require login, tenancy, Hosted
deployment, Temporal orchestration, or an operations product. Continuing to
preserve those implementation dependencies prevents the four core resources
from forming one understandable, persistent, testable product.

## Accepted Target

The authority for this effort is:

- [`docs/architecture/core.md`](../../docs/architecture/core.md)
- [`ADR-0151`](../../docs/adr/0151-make-module-first-core-the-only-active-runtime.md)
- [`CONTEXT.md`](../../CONTEXT.md)

The product loop is:

```text
Data Update
-> Dataset Release
-> Save Research Definition
-> Run
-> inspect Factor and Strategy/Benchmark Result
-> Rerun or Start DailyTrack
-> publish a later Release
-> automatic Track advance
-> blocked Retry or terminal Stop
```

There is one Core runtime, one product interface, one Web application, one
PostgreSQL Product State, and one standard S3-compatible immutable-object
implementation. Pinned RustFS supplies S3 in development and continuous
integration. Fixture and Tushare are DataSource adapters, not product modes.

## Delivery Rules

- Work the dependency frontier. A ticket may start when every ticket named in
  its `Blocked by` field is complete; numbering gives stable dependency order,
  not an artificial single-file queue.
- Each issue must deliver an observable vertical slice through the highest
  relevant seam. Do not call a module complete based only on private unit tests.
- Every issue records `How to verify`: the command or operator scenario that
  demonstrates its acceptance criteria and the outcome that must be observed.
  A ticket does not need a unique Make target merely to be independently
  verifiable.
- Preserve existing quantitative semantics with characterization tests before
  moving code. Do not rewrite validated Alpha, Factor, Strategy, or numeric
  behavior merely to fit the new directories.
- New Core code may not import `thesistrace.hosted`, old lifecycle facades, or a
  global metadata interface.
- Do not create a compatibility layer intended to survive the cutover.
- Do not delete Hosted V2 code until an explicit Git archive ref has been
  created and the new browser flow is accepted.
- Use `uv` for Python and `bun` for TypeScript/JavaScript.
- Preserve unrelated working-tree changes throughout implementation.

## Issue Map

1. `01-archive-hosted-v2-baseline.md`
2. `02-characterize-quantitative-behavior.md`
3. `03-open-canonical-empty-core-runtime.md`
4. `04-expand-normalized-alpha-expression-contract.md`
5. `05-prepare-and-read-immutable-publication-bytes.md`
6. `06-record-publication-atomically-in-postgresql.md`
7. `07-extract-research-kernel-run.md`
8. `08-extract-research-kernel-advance.md`
9. `09-prove-kernel-once-versus-chunked-equivalence.md`
10. `10-publish-first-fixture-dataset-release.md`
11. `11-publish-later-dataset-release.md`
12. `12-complete-idempotent-no-change-data-update.md`
13. `13-recover-failed-data-publication-after-restart.md`
14. `14-migrate-tushare-to-canonical-datasource.md`
15. `15-save-and-reopen-incomplete-definition.md`
16. `16-author-alpha-with-authoritative-options.md`
17. `17-protect-definition-edits.md`
18. `18-reject-non-runnable-run-while-saving.md`
19. `19-admit-valid-run-with-immutable-input.md`
20. `20-execute-and-publish-queued-research-run.md`
21. `21-show-bounded-research-run-result.md`
22. `22-recover-abandoned-and-duplicate-run-execution.md`
23. `23-exhaust-research-run-retries-safely.md`
24. `24-cancel-research-run-and-fence-late-work.md`
25. `25-rerun-exact-immutable-input.md`
26. `26-start-and-reopen-one-daily-track.md`
27. `27-advance-track-by-direct-successor.md`
28. `28-catch-up-track-in-order.md`
29. `29-recover-concurrent-and-interrupted-track-progression.md`
30. `30-rebuild-working-cache.md`
31. `31-prove-persisted-batch-incremental-equivalence.md`
32. `32-show-recent-and-cumulative-track-analysis.md`
33. `33-block-one-failed-track-independently.md`
34. `34-retry-same-failed-track-target.md`
35. `35-stop-daily-track-irreversibly.md`
36. `36-harden-daily-track-activation-admission.md`
37. `37-cut-over-canonical-core-backend.md`
38. `38-cut-over-four-resource-web-shell.md`
39. `39-remove-old-web-and-authentication-surface.md`
40. `40-remove-hosted-execution-and-orchestration.md`
41. `41-remove-hosted-operations-and-observability-runtime.md`
42. `42-remove-hosted-identity-and-deployment-runtime.md`
43. `43-remove-custom-storage-proxies-and-hosted-glue.md`
44. `44-remove-legacy-daily-track-and-cache-paths.md`
45. `45-remove-legacy-definition-and-run-paths.md`
46. `46-remove-legacy-data-and-publication-paths.md`
47. `47-remove-orphaned-legacy-infrastructure.md`
48. `48-prove-post-contraction-architecture-invariants.md`
49. `49-prove-core-closure-from-clean-state.md`

## Required Final Verification

The final `make check` must start or address an isolated, real PostgreSQL and
pinned RustFS test runtime and then run:

```text
tests/kernel/
tests/architecture/
tests/adapters/
tests/integration/
tests/acceptance/
desktop browser acceptance
```

The command must not run Hosted, login, tenancy, production-deployment, or live
Tushare checks. It must not silently replace PostgreSQL or RustFS with SQLite,
an in-memory store, or fake S3.

Live Tushare verification belongs to an explicit `make check-live-tushare`
gate. Offline adapter-contract tests may remain in the default gate but are not
evidence of live credentials, permissions, freshness, or publication.

## Final Acceptance Scenario

From clean PostgreSQL schemas and an empty bucket, the browser and public HTTP
interface must prove:

1. Data Update publishes the first Fixture Dataset Release.
2. A nameless, incomplete Definition can be saved and reopened.
3. Run rejection saves the current revision and creates no ResearchRun.
4. Corrected content creates a queued Run that succeeds and shows Factor plus
   Strategy/Benchmark conclusions.
5. Editing and running the Definition again creates an independent Run.
6. Rerun creates a new ID with the original immutable input and Release.
7. Cancel prevents a late worker result from becoming visible.
8. A successful Run starts at most one DailyTrack.
9. A later Data Update publishes normally and advances the Track.
10. A failed Track becomes blocked without moving Head; Retry recovers the same
    target; Stop is irreversible.
11. Restarting HTTP and worker processes preserves every product resource and
    authoritative publication.

## Out of Scope

- Login, Auth Session, InsForge, User, Personal Workspace, RLS, RBAC, or
  invitations.
- Hosted deployment, Cloudflare, Caddy, Temporal, production backup, alerting,
  capacity qualification, and launch evidence.
- Organizations, collaboration, billing, notifications, downloads, raw object
  access, or cross-ResearchRun comparison.
- Qlib, broker execution, arbitrary Python/SQL, dynamic operator plugins, or a
  second Strategy implementation.

## Completion

This effort is complete only when issue 49 passes after legacy and Hosted
runtime removal. Passing focused tests, retaining an old runtime fallback, or
demonstrating only the Kernel is not Core closure.
