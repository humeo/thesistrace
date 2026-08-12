# 04 — Materialize the 2010 Point-in-Time Financial candidate

**What to build:** Convert complete Raw Financial Batches into one validated,
unpublished equity.financial_pit candidate that preserves every accepted source
field and version while declaring trustworthy Financial Coverage from the first
Research Session of 2010. The candidate must distinguish source evidence,
Canonical version facts, information time, sparse missingness, and the minimal
pre-start seeds required by later research fields.

**Blocked by:** 03 — Collect and checkpoint Raw Financial Batches.

**Status:** complete

- [x] Income statements, balance sheets, and cash-flow statements materialize
  as three separate nullable wide version tables with every field in the pinned
  source contract.
- [x] Every version preserves Instrument Identity, endpoint, report period,
  report type, company type, end type, announcement dates, update marker,
  availability, revision basis, row digest, and Raw Financial Batch digest.
- [x] Exact source-row identity is idempotent while different payload versions
  in the same logical revision group coexist.
- [x] All returned report types and company types are retained; update markers
  do not overwrite or delete older versions.
- [x] Final announcement date is preferred over announcement date for source
  publication, and date-level publication maps to the next completed Research
  Session.
- [x] A same-date payload change with no new verifiable source publication date
  is an observed correction visible no earlier than its first observation
  session.
- [x] A row without a usable publication date is quarantined and cannot enter
  authorable Point-in-Time Financial Data.
- [x] Source nulls remain null and are never filled with zero.
- [x] Financial Coverage Start is the first Research Session of 2010 and the
  expected collection set includes historical, including delisted, ordinary
  A-shares.
- [x] Canonical facts include every version becoming available on or after
  Coverage Start plus only the latest required pre-start annual and
  balance-sheet seed facts.
- [x] Older response rows not selected as seeds remain Raw Financial Batch
  evidence and do not extend Canonical Coverage backward.
- [x] The financial family Manifest records complete shard evidence,
  observation-through cutoff, historical reconciliation, and source
  revision-coverage limitations.
- [x] Sparse missing facts for individual instruments do not make the family
  candidate incomplete.
- [x] The candidate can be reopened and revalidated deterministically but
  cannot move the Dataset Head or appear in ordinary Alpha authoring.

## Comments

- Parent: Point-in-Time Financial Data and Composite Alpha.
