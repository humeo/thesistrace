# 01 — Materialize Family Manifest market candidates

**What to build:** Give the Data Operator a verifiable candidate-storage path
that represents the current market dataset as one Data Generation root pointing
to family Manifests. The candidate path must preserve the current market
meaning, content reuse, family-specific Coverage, and descriptor-only
inspection without changing the active runtime or publishing a new Head. This
is the prefactor that makes the later hard cut and financial family addition
small enough to execute safely.

**Blocked by:** None — can start immediately.

**Status:** complete

- [x] A deterministic current-market fixture can be materialized as one root
  descriptor with explicit family Manifest references and family-specific
  Dataset Coverage.
- [x] Reopening the candidate after process restart reproduces the same
  descriptors, Dataset Schemas, Coverage declarations, field availability, and
  content identities.
- [x] Root inspection returns the metadata required by admission and Data
  Overview without opening any Parquet Physical Data Object.
- [x] Identical source content reuses identical family Manifests and Physical
  Data Objects rather than rewriting equivalent bytes.
- [x] Reordered but semantically identical input produces the same canonical
  content identities.
- [x] Missing, corrupt, mismatched, or incompletely synchronized family
  descriptors fail validation and never appear as a complete candidate.
- [x] Family Coverage is not collapsed into one universal date range at the
  root.
- [x] Candidate creation and validation use real immutable filesystem objects
  and deterministic fixtures.
- [x] Building the candidate does not move the current Dataset Head and does
  not introduce a runtime fallback or compatibility reader.
- [x] Existing active market ResearchRun and DailyTrack behavior remains
  unchanged while this candidate-only path is introduced.

## Comments

- Parent: Point-in-Time Financial Data and Composite Alpha.
- This is the one explicit prefactor ticket; Ticket 02 performs the runtime
  hard cut.
- Implemented a candidate-only root-to-Family Manifest graph with explicit
  market Family schemas, family-owned Coverage, validation summaries, and
  canonical `equity.eod_price` / `equity.adjustment_factor` /
  `equity.trading_state` boundaries. The active flat Head/runtime is unchanged.
- Validation decodes every Physical Data Object, verifies schema, canonical
  bytes, boundaries, partitions, row counts, current canonical invariants, and
  recomputed root/Family projections. Inspection remains descriptor-only.
- Verification: focused mounted-generation suite `30 passed`; repository gate
  `314 passed` with one existing warning; frontend typecheck and `9 passed`.
- Standards and Spec reviews were run independently. All findings were fixed
  and both final re-reviews reported no remaining actionable findings.
