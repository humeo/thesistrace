# 04 — Trace Data Refresh phases safely

**What to build:** Give the Data Operator a correlated, safe phase timeline for
one Data Refresh while preserving stdout as the clean machine-readable command
result. Operators can distinguish Market, Financial, validation, publication,
and total outcome without exposing source credentials or Dataset internals.

**Blocked by:** 01 — Emit safe structured HTTP events

**Status:** ready-for-agent

- [ ] Data Refresh operational events use the canonical JSON contract on stderr and carry `operation_id`.
- [ ] The observable lifecycle covers operation start, Market completion, Financial completion, validation completion, Dataset Generation publication, total success, and failure for the phases actually executed.
- [ ] Each completed phase and total outcome records bounded `duration_ms` and a safe outcome without raw payloads.
- [ ] Publication success is emitted only after the new immutable Data Generation is valid and the Dataset Head movement has committed.
- [ ] Retryable dependency degradation is WARNING, normal phase progress is INFO, and unexpected or terminal internal failure is ERROR.
- [ ] Data Operator stdout remains exactly one machine-readable command result and contains no operational event line.
- [ ] Tushare tokens, database credentials, DSNs, source request or response data, SQL, instrument payloads, Dataset manifests, object keys, physical paths, and raw exception messages never appear in stderr events.
- [ ] Existing direct progress printing and ad hoc Data Refresh operational output are removed from the affected path without a compatibility emitter or alternate schema.
- [ ] Tests cover Market-only, Financial-only, combined, validation, publication, and sanitized failure outcomes while asserting stdout and stderr remain independently parseable.
- [ ] Real dependency integration proves emitted success facts agree with the published Dataset Head and that failed publication emits no success event.
- [ ] Data Update, overlap merge, immutable Generation, Head movement, and garbage-collection semantics remain unchanged.

## Comments

- Parent: Basic Operational Observability.
