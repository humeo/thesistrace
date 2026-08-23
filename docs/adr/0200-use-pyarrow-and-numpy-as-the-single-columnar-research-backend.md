---
status: accepted
---

# Use PyArrow and NumPy as the single columnar Research backend

The canonical Research executor uses PyArrow for Parquet scanning, projection,
filtering, Arrow buffers, null masks, and RecordBatch interchange, and NumPy for
vectorized numeric kernels that PyArrow does not directly provide. Canonical
Market and Financial Data are read only for the current ResearchRun Execution
Chunk, required fields, and relevant Universe membership. Rows are ordered
deterministically by Research Session and instrument before order-sensitive
calculation.

Alpha plan nodes consume typed columnar arrays and release dead intermediates
inside the Chunk. Whole Arrow tables or RecordBatches never pass through
`to_pylist()`, full-period Python dictionaries, or defensive deep-copy graphs.
Strategy execution may extract the bounded scalar or compact per-session state
required by its sequential domain rules without converting the full Chunk to
Python rows.

This backend runs inside the single supervised execution child. The child reads
only the frozen mounted Canonical Data Generation and returns bounded Chunk
continuation and result data; the Research Worker supervisor remains the only
component allowed to validate and durably commit checkpoints, staged Result
objects, and final publication.

All dtype conversion, null handling, sorting, floating-point operations, and
serialization remain explicit parts of the Numeric Execution Contract. A
zero-copy view is used where valid, but correctness and stable missingness take
priority over avoiding a required bounded copy.

This implements ADR-0131's bounded-memory columnar requirement and ADR-0164's
series execution plan. ThesisTrace has no Polars, DuckDB, SQL execution route,
or versioned alternate engine.
