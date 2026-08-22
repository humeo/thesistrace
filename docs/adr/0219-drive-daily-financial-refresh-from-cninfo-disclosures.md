---
status: accepted
---

# Drive daily financial refresh from CNINFO disclosures

After the initial complete-history bootstrap, ThesisTrace refreshes financial
data from CNINFO announcement discovery through a pinned AKShare adapter rather
than rebuilding every Tushare statement shard each day. Discovery queries
`年报`, `半年报`, `一季报`, `三季报`, and `补充更正` with at least a seven-natural-day
overlap plus every unresolved query gap; each deduplicated current instrument
then receives one atomic refresh of the ordinary Tushare income, balance-sheet,
and cash-flow endpoints. CNINFO supplies discovery evidence only, while Tushare
remains the sole source of Canonical financial values and no provider fallback
is allowed.

Publication is best-effort across instruments but fail-closed within one
instrument. Successful instruments publish together; a failed or not-yet-synced
instrument retains its prior facts, or remains missing when none exist, and is
retried on the next trading-day refresh. A trigger closes on a matching Tushare
source version with the same report period and publication date in any member of
the accepted three-statement snapshot, or after five successive accepted
three-statement refreshes with no matching structured change. An announcement
whose report period cannot be derived cannot match merely because another report
was published on the same date. A newly observed source row that cannot enter the
PIT projection rejects only that instrument. Announcement category or page
failures publish as explicit discovery gaps rather than being hidden or blocking
unrelated facts.

Daily materialization is incremental over the previously validated immutable
Financial Family. A zero-trigger refresh reuses its table objects, Raw Evidence
index, and quarantine summary exactly. An accepted instrument reads only that
instrument's prior Raw Evidence, projects the union with its new atomic
three-statement snapshot, and appends only new or changed Canonical rows as
content-addressed delta objects. The new table manifest retains an explicit
base-manifest link; reads overlay a repeated `source_row_sha256` with the later
delta row, while source absence never deletes a previously observed version.
Validation replays only the affected instruments and verifies the immutable
base prefix, and Garbage Collection retains the parent Family and table-base
manifest chain. This avoids moving the former complete-history rebuild from
remote request time into local Parquet CPU and I/O.

Financial Coverage therefore separates Attempted Through from Complete Through
and carries discovery gaps, pending instruments, the last historical
reconciliation watermark, and revision limitations. Financial Research
Readiness is `ready`, `ready_with_pending`, `ready_with_gaps`, or `not_ready`;
the first three permit ResearchRun and DailyTrack execution while recording the
quality state and using prior or missing facts. Point-in-time facts retain both
source-derived availability and first-observed time: later Generations may use a
late-ingested report from its true source availability, but completed DailyTrack
progressions remain pinned and are never rewritten.

The complete-history bootstrap observation-through session initializes both
discovery coordinates without pretending that CNINFO was queried historically.
The announcement-driven contract begins after that Financial Discovery Baseline;
the initial 2026-08-13 validation copy is one instance of the rule, not a date
embedded in the product.

This decision supersedes ADR-0185 in full. It supersedes only ADR-0009's claim
that Tushare is the sole external evidence source, ADR-0180's complete-shard
publication rule for post-bootstrap daily refresh, and ADR-0183's all-or-nothing
Financial Coverage and DailyTrack blocking rule. Their source-neutral boundary,
ordinary per-instrument Tushare transport, one Dataset Head, and family-owned
Coverage decisions remain in force.

## Consequences

The daily path no longer discovers silent historical Tushare corrections that
have no selected CNINFO announcement, so the historical reconciliation
watermark remains at the bootstrap or last explicitly completed reconciliation.
AKShare's CNINFO transport has no product SLA. The adapter bounds each underlying
request to 30 seconds; timeout, schema, category, and pagination failures are
preserved as degraded evidence and retried without fallback. This decision adds
no scheduler: the idempotent Financial Refresh remains a private, manually
invoked Data Operator action.
