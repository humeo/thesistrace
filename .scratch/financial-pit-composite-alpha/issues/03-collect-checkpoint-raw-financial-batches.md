# 03 — Collect and checkpoint Raw Financial Batches

**What to build:** Give the private Data Operator one deterministic,
restartable way to collect complete historical income, balance-sheet, and
cash-flow responses for the historical ordinary A-share Instrument Identity
set. Each accepted response must become immutable source evidence, while
permission, completeness, schema, and rate failures remain explicit and cannot
publish or silently select another transport.

**Blocked by:** 01 — Materialize Family Manifest market candidates.

**Status:** complete

- [x] The deployment capability probe records ordinary endpoint permission,
  returned fields, null and duplicate behavior, response boundaries, and
  observed rate-limit behavior for all three statement endpoints.
- [x] The collector uses only the ordinary per-instrument endpoints and one
  fixed endpoint-by-instrument shard contract.
- [x] The expected shard set uses historical ordinary A-share identities rather
  than only currently active listings.
- [x] If one complete-history response cannot be proven complete, collection
  accepts only one preselected deterministic date-shard contract and never
  changes request shape at runtime.
- [x] Every completed shard has a durable checkpoint that allows restart to
  resume unfinished work without accepting a completed shard twice.
- [x] Every accepted response is retained as a content-addressed Raw Financial
  Batch with endpoint, parameters, returned field order, collection time, row
  count, source-date extent, and payload digest.
- [x] An exact replay of the same response is idempotent and reuses the same
  evidence object.
- [x] Permission denial, suspected truncation, malformed fields, schema drift,
  rate exhaustion, or partial endpoint failure prevents successful collection
  completion.
- [x] Progress and failure diagnostics identify the endpoint, instrument, and
  shard without exposing the TuShare token or sensitive configuration.
- [x] Deterministic Stub or Replay tests cover success, duplicates, nulls,
  retry, interruption, resume, and fail-closed behavior without public network
  access.
- [x] Completing collection creates no authorable financial field and does not
  move the Dataset Head.

## Comments

- Parent: Point-in-Time Financial Data and Composite Alpha.
- A live deployment-token probe is operational evidence, not a CI dependency.
