# 04 — Trace Data Refresh phases safely

**What to build:** Give the Data Operator a correlated, safe phase timeline for
one Data Refresh while preserving stdout as the clean machine-readable command
result. Operators can distinguish Market, Financial, validation, publication,
and total outcome without exposing source credentials or Dataset internals.

**Blocked by:** 01 — Emit safe structured HTTP events

**Status:** complete

- [x] Data Refresh operational events use the canonical JSON contract on stderr and carry `operation_id`.
- [x] The observable lifecycle covers operation start, Market completion, Financial completion, validation completion, Dataset Generation publication, total success, and failure for the phases actually executed.
- [x] Each completed phase and total outcome records bounded `duration_ms` and a safe outcome without raw payloads.
- [x] Publication success is emitted only after the new immutable Data Generation is valid and the Dataset Head movement has committed.
- [x] Retryable dependency degradation is WARNING, normal phase progress is INFO, and unexpected or terminal internal failure is ERROR.
- [x] Data Operator stdout remains exactly one machine-readable command result and contains no operational event line.
- [x] Tushare tokens, database credentials, DSNs, source request or response data, SQL, instrument payloads, Dataset manifests, object keys, physical paths, and raw exception messages never appear in stderr events.
- [x] Existing direct progress printing and ad hoc Data Refresh operational output are removed from the affected path without a compatibility emitter or alternate schema.
- [x] Tests cover Market-only, Financial-only, combined, validation, publication, and sanitized failure outcomes while asserting stdout and stderr remain independently parseable.
- [x] Real dependency integration proves emitted success facts agree with the published Dataset Head and that failed publication emits no success event.
- [x] Data Update, overlap merge, immutable Generation, Head movement, and garbage-collection semantics remain unchanged.

## Comments

- Parent: Basic Operational Observability.
- Added one non-blocking canonical lifecycle for Market and Financial Refresh:
  safe operation identity, phase completion, bounded duration, committed
  publication, total outcome, persisted retry/failure, fencing, heartbeat
  failure, and post-CAS recovery facts. Successful publication is observed only
  after Dataset Head and operation completion commits.
- Hard-cut the old `refresh_timing` and `financial_refresh` progress callbacks
  from both Refresh services. Data Operator keeps stdout for one command result;
  operational JSONL remains on stderr. A failure before an operation starts
  returns one safe stdout result without inventing an uncorrelated event.
- Initial reviews found the retained alternate progress schema, synchronous
  telemetry changing post-commit semantics, a silent Market reconciliation,
  Financial completion-pending classified as WARNING, and a duplicate
  uncorrelated command ERROR. All were fixed. The private EntryPoint mock added
  during repair was replaced with public subprocess coverage. Final independent
  Standards and Spec re-reviews were clean.
- Verification: Ruff and diff-check passed; complete backend fast lane 539
  passed with 5 existing warnings; Data Operator EntryPoint lane 8 passed;
  public Market/Financial pre-operation failure subprocess lane 2 passed; fresh
  isolated real PostgreSQL/RustFS Market lane 18 passed and Financial lane 29
  passed; Web typecheck passed; Web shell lane 56 passed. The isolated Docker
  projects, volumes, networks, and temporary data directories were removed.

## Plan

1. Replace the Data Operator's direct progress printer with the canonical
   stderr event adapter while keeping stdout reserved for exactly one command
   result and removing uncorrelated source-level timing output from Refresh.
2. Emit non-blocking Market Refresh facts from the service that owns the claim:
   operation start, completed Market/validation/materialization/publication
   phases with bounded milliseconds, committed total outcome, and persisted
   retryable versus terminal failure.
3. Give Financial Refresh one stable safe operation identity and emit its
   Financial, validation, committed publication, total success, and sanitized
   failure facts without manifests, object keys, paths, source payloads, or raw
   exception messages.
4. Add contract tests for Market-only, Financial-only, combined publication,
   no-change, validation failure, publication failure, stdout/stderr separation,
   safe canaries, telemetry loss, and agreement between success events and the
   committed Dataset Head using real PostgreSQL and RustFS.
5. Run focused real-dependency lanes, Ruff, the complete fast backend lane and
   Web gates; complete independent Standards and Spec reviews, fix and
   re-review, update this tracker, and create one Ticket 04 commit.
