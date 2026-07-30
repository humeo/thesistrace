---
status: accepted
---

# Require canonical exact Batch-Incremental Equivalence

For the same Tracking Origin, research semantics, ordered sequence of Advance
Dataset Releases, Tracking Generation, and pinned runtime and numeric
contracts, the reference oracle and incremental DailyTrack must produce
canonically exact results:

- missingness, reason codes, Universe Membership, ranks, orders, quantities,
  holdings, and state transitions are identical;
- decimal fees, cash, accounting values, and serialized NAV outputs are
  identical; and
- `float64` outputs have identical canonical serialized values after normalizing
  negative zero to zero.

ADR-0109 defines the accounting decimal context, canonical integer and decimal
encodings, binary64 byte encoding, and the versions pinned by a DailyTrack and
Tracking Generation. Display formatting is not part of equivalence.

Batch and incremental execution use the same calculation kernel, canonical
input ordering, and deterministic tie rules. A newly appended Alpha uses its
complete ordered input window instead of an error-accumulating online
recurrence. After inserting newly mature observations and evicting observations
outside the latest 504 signal sessions, Factor summaries are recomputed in one
canonical order from ADR-0148's bounded Rolling Factor Observation Cache.
Strategy aggregates are recomputed from the retained ordered Strategy series;
neither path uses a differently ordered online statistic.

Runtime Alpha Values, Forward Return Labels, daily Factor observations, orders,
and fills may be instrumented and compared during equivalence verification
without becoming durable Result or Checkpoint artifacts. A missing operational
Working Cache is rebuilt over its bounded window from immutable Dataset
Releases and pinned research semantics, following the exact Release sequence
bound by the Checkpoint chain. Ordinary Advances, including ADR-0144
correction-boundary Advances, do not full-replay from Tracking Origin. ADR-0109
separately governs a result-changing calculation-kernel correction.

The reference oracle applies each Dataset Release to the same Research Sessions
processed by the corresponding Advance and carries forward the same committed
Checkpoint state. After an ADR-0144 correction boundary, computing from the
Tracking Origin against only the latest corrected Release describes a
counterfactual path and is not the equivalence comparator. A difference from
that counterfactual is neither an invariant failure nor evidence that the
accepted Track is irreproducible.

V1 verifies this invariant through historical release-sequence tests and
explicit equivalence verification. An ordinary successful daily Advance does
not also run a full reference execution, so the correctness contract does not
turn every post-close update into a full-history computation. A detected
mismatch under the same ordered Release sequence is a failed equivalence
verification and may not be accepted as "close enough" under a numeric
tolerance.
