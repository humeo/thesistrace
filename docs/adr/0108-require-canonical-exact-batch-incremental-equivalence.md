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
recurrence. Factor and Strategy aggregates are recomputed from their retained
ordered observation series rather than through a differently ordered online
statistic.

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
