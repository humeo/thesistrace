# Financial Refresh operational telemetry

Status: ready-for-agent

## Scope

Expose live, bounded, read-only Financial Refresh diagnostics in the Operator
receipt and history details. Reuse persisted discovery evidence and per-company
attempt checkpoints; do not change collection, retry, publication, or schemas.

- Show discovery/collection/publication phase, elapsed time, last progress time,
  discovered announcements, processed companies, companies with Canonical changes,
  companies with no Canonical changes, and failed companies.
- A company's three-statement collection and Canonical validation must finish
  before it counts. Counts survive polling/restarts without double counting.
- No fabricated total-company denominator or whole-operation percentage.
  Discovery gaps mean the full affected-company population is unknown.
- Surface each operation's immutable discovery gap category, query dates, and
  safe reason code, even if a later operation resolves the gap.
- Counts are not publication: only the existing terminal receipt says published.
- Use the existing five-second visible-page poll, including stale/error messaging.
- No new database columns, migrations, compatibility paths, source calls, or
  live refresh submissions. Preserve unrelated skills work.

## Evidence

`financial-20260904T063104Z` requested 2026-08-17 and published degraded success
after ~30 seconds. Four accepted companies matched ten announcements; no company
failed. CNINFO half-year announcement discovery for 2026-08-08..2026-08-17 failed
with `CNINFO_DISCOVERY_UNAVAILABLE`. Unverified dates start on 2026-08-15, so
complete-through remains 2026-08-14. The adapter stores a network-error category,
not enough evidence to distinguish timeout from a connection/requests error.

## Verification

Real isolated PostgreSQL regression: before discovery, partial company processing,
no-change/failure, publication, retry without double counting, terminal retention,
exact operation isolation, no private payload leakage. HTTP safe-schema/permission
contracts, strict browser decoders, receipt/history rendering and browser layout.
