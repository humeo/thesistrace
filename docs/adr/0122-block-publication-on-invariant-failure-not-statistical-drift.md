---
status: accepted
---

# Block publication on invariant failure, not statistical drift

Every immutable publication boundary distinguishes deterministic correctness
invariants from statistical drift.

A failed correctness invariant is a hard gate:

- invalid schema, keys, lineage, canonical checksums, or mandatory market-data
  consistency prevents a Dataset Release from being published;
- a violated numeric contract, accounting invariant, canonical checksum, or
  required release-sequence Batch-Incremental Equivalence check prevents the
  affected Result Bundle or Tracking Checkpoint from being published; and
- a failed candidate never moves the Dataset latest pointer or Tracking Head.

After an ADR-0144 correction boundary, a comparison that applies only the
latest corrected Dataset Release from the Tracking Origin is not a required
equivalence check and cannot block the prospective Tracking Advance.

The previously published immutable Release, Result, Generation, or Checkpoint
remains available. A failed attempt records attributable, operator-visible
evidence and a stable sanitized failure for its owning User where applicable.

The first hosted release does not preserve a per-artifact Validation Summary or
a validation-contract version solely to prove why a historical artifact was
accepted. Successful publication means that the active hard gates passed.
Domain manifests retain only facts required by their domain contracts; Attempt
diagnostics, logs, metrics, and traces follow their normal operational
retention.

Statistical changes such as unusual Alpha distributions, coverage movement,
Factor metrics, or Strategy turnover are not correctness failures by
themselves. They emit observable drift evidence and a dashboard warning but do
not automatically block publication, because real market behavior can produce
the same changes. A later explicit policy may promote a specific bounded
condition to a correctness invariant; warning evidence alone does not do so.
