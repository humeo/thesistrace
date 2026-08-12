# 01 — Materialize Family Manifest market candidates

**What to build:** Give the Data Operator a verifiable candidate-storage path
that represents the current market dataset as one Data Generation root pointing
to family Manifests. The candidate path must preserve the current market
meaning, content reuse, family-specific Coverage, and descriptor-only
inspection without changing the active runtime or publishing a new Head. This
is the prefactor that makes the later hard cut and financial family addition
small enough to execute safely.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] A deterministic current-market fixture can be materialized as one root
  descriptor with explicit family Manifest references and family-specific
  Dataset Coverage.
- [ ] Reopening the candidate after process restart reproduces the same
  descriptors, Dataset Schemas, Coverage declarations, field availability, and
  content identities.
- [ ] Root inspection returns the metadata required by admission and Data
  Overview without opening any Parquet Physical Data Object.
- [ ] Identical source content reuses identical family Manifests and Physical
  Data Objects rather than rewriting equivalent bytes.
- [ ] Reordered but semantically identical input produces the same canonical
  content identities.
- [ ] Missing, corrupt, mismatched, or incompletely synchronized family
  descriptors fail validation and never appear as a complete candidate.
- [ ] Family Coverage is not collapsed into one universal date range at the
  root.
- [ ] Candidate creation and validation use real immutable filesystem objects
  and deterministic fixtures.
- [ ] Building the candidate does not move the current Dataset Head and does
  not introduce a runtime fallback or compatibility reader.
- [ ] Existing active market ResearchRun and DailyTrack behavior remains
  unchanged while this candidate-only path is introduced.

## Comments

- Parent: Point-in-Time Financial Data and Composite Alpha.
- This is the one explicit prefactor ticket; Ticket 02 performs the runtime
  hard cut.
