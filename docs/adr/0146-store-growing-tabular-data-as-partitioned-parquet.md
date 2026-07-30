---
status: accepted
---

# Store growing tabular data as partitioned Parquet

ThesisTrace selects physical encoding by payload growth shape. Manifests,
configuration, provenance, and bounded summaries remain canonical JSON. Any
payload that grows with Research Sessions multiplied by instruments, or with an
unbounded event stream, must not be stored as one nested JSON document:
Canonical Market Data and retained Strategy observations and aggregates use
Parquet compressed with ZSTD. Runtime Alpha Matrix values, Forward Return
Labels, daily Factor observations, raw orders, fills, and diagnostic events are
not durable result objects under ADR-0147 and ADR-0148.

For each instrument-by-session Canonical Dataset Family, the immutable
publication unit is one Research Session. Its logical partition keys are
`dataset_family/year/month/trade_date`, and rows are ordered by
`instrument_id`. Dataset Bootstrap creates the same daily units in bounded
batches while covering the complete three-year Research Input History and
required earlier dependencies. Later Dataset Publication appends only new
daily units; a catch-up release emits one unit per missing session, and an
accepted correction replaces only its affected family-session unit in the next
normal release. V1 does not add monthly compaction.

This preserves immutable, reproducible Physical Data Objects while permitting
partition and column pruning and avoiding the repeated field names and
full-document materialization required by nested JSON. One ResearchRun stores
each bounded retained Strategy table as one ZSTD Parquet object rather than
one file per Research Session. One Tracking Advance stores only its newly
retained Strategy observation and aggregate rows, never a copy of the
Generation's complete history.

The non-authoritative DailyTrack Working Cache uses canonical JSON for its
basis record and ZSTD Parquet for its two tabular payloads. Pending Alpha is
partitioned by signal session with at most one file per session and
approximately 21 files; Rolling Factor observations use one compact file with
at most 1,512 rows. These replaceable cache files are not immutable Physical
Data Objects.

This decision does not choose the encoding of accepted upstream source
evidence. It also leaves row-group targets, the Parquet writer contract, and
semantic-versus-byte identity of immutable Physical Data Objects to later
decisions.
