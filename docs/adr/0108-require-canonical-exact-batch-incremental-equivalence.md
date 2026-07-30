---
status: accepted
---

# Require canonical exact Batch-Incremental Equivalence

For the same Tracking Origin, research semantics, target Dataset Release,
Tracking Generation, and pinned runtime and numeric contracts, the batch oracle
and incremental DailyTrack must produce canonically exact results:

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

V1 verifies this invariant through historical session-by-session replay tests
and explicit equivalence verification. An ordinary successful daily Advance
does not also run a full batch replay, so the correctness contract does not
turn every post-close update into a full-history computation. A detected
mismatch is a failed equivalence verification and may not be accepted as
"close enough" under a numeric tolerance.
