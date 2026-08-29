# 01 — Publish an independent CSI 300 Benchmark Snapshot

**What to build:** Publish one complete, atomically replaced JSON Benchmark
Snapshot outside Canonical Data. Bootstrap and Market Refresh must ensure the
Snapshot covers every Market Research Session before publishing a Market Head.

**Blocked by:** None.

**Status:** complete

- [x] Fix Tushare `index_daily`, `399300.SZ`, and `open` under one source-neutral contract.
- [x] First publication collects 2010-01-04 through target Market Coverage; later publications request and append only sessions after the Snapshot terminal session.
- [x] Strict reading rejects missing, duplicate, unordered, non-positive, non-finite, malformed, or insufficient Levels.
- [x] Rewriting the complete JSON uses a same-directory temporary file, flush/fsync, and atomic rename; failed publication preserves the prior Snapshot.
- [x] Dataset Bootstrap and Market Refresh publish Snapshot first and Market Head second; a Snapshot may lead but a new Market Head may not lead it.
- [x] Market no-change can still publish a missing or lagging Snapshot.
- [x] `benchmark-data` is independent of `canonical-data`; API/Data Operator mount it read-write and Research, Batch, and Tracking Workers do not mount it.
- [x] Focused source, replay, store, append, idempotency, coverage, publication-order, and lifecycle tests pass.

## Comments

- Implemented the independent append-only Snapshot Store, source/replay path,
  Benchmark-first Market publication, and isolated lifecycle volume contract.
- Verification: `mise exec -- pnpm test` passed 666 backend tests, TypeScript
  typecheck, and 63 frontend tests. `mise exec -- pnpm test:integration` passed
  289 integration tests plus all six restart/recovery sentinels under isolated
  Compose run `20260827t120314z-21237-79249013`.
- Standards review and Spec review both completed clean after adding durable
  publication recovery and cross-process locking for concurrent readers.
