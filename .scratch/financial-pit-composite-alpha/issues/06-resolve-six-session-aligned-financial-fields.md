# 06 — Resolve six Session-Aligned Financial Fields

**What to build:** Let callers resolve the six approved financial meanings from
a pinned financial candidate into storage-independent Numeric Series for
specific instruments and Research Sessions. The same Data-owned boundary must
serve research and tracking without exposing physical tables, source columns,
or point-in-time joins to the Research Kernel.

**Blocked by:** 02 — Cut the market runtime to selective Series reading; 04 —
Materialize the 2010 Point-in-Time Financial candidate.

**Status:** complete

- [x] The Field Catalog exposes revenue,
  net_profit, operating_cash_flow,
  assets, liabilities, and
  equity as stable Alpha Identifiers, each bound to a
  namespaced `financial.<statement>...` Field Reference.
- [x] Each field declares its family, numeric type, monetary unit, information
  time, reporting scope, report-period selection, missingness, source lineage,
  and applicable company types.
- [x] The three flow fields select only the latest visible full-year
  report-type-1 consolidated facts.
- [x] The three stock fields select only the latest visible quarterly or annual
  report-type-1 consolidated balance-sheet facts.
- [x] All six fields apply to company types 1, 2, 3, and 4 without promising a
  non-null value.
- [x] Source versions, observed corrections, and pre-2010 seed facts change the
  resolved Series only from their defined availability sessions.
- [x] Missing statements and source nulls remain missing and do not trigger
  fallback to another report type, reporting scope, company-specific field,
  zero, or a changed Liquidity Universe.
- [x] No TTM, interim cumulative, single-quarter, vendor ratio, per-share, or
  other retained source field becomes authorable.
- [x] One batched request resolves only the requested Field References,
  sessions, and instruments into aligned storage-independent Series.
- [x] Financial reads project only required statement columns and relevant
  availability partitions rather than scanning every field or one file per
  instrument.
- [x] The Research Kernel consumes the same Alpha input shape for market and
  financial fields and contains no financial storage or as-of logic.
- [x] Deterministic contract tests cover revisions, holidays, seeds, missing
  values, all company types, and mixed requested field sets.

## Comments

- Parent: Point-in-Time Financial Data and Composite Alpha.
