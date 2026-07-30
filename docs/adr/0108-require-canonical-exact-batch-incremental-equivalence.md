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
recurrence. After inserting newly mature observations and evicting observations
outside the latest 504 signal sessions, Factor summaries are recomputed in one
canonical order from ADR-0148's bounded Rolling Factor Observation Cache.
Strategy aggregates are recomputed from the retained ordered Strategy series;
neither path uses a differently ordered online statistic.

Runtime Alpha Values, Forward Return Labels, daily Factor observations, orders,
and fills may be instrumented and compared during equivalence verification
without becoming durable Result or Checkpoint artifacts. A missing operational
Working Cache is rebuilt over its bounded window from immutable Dataset Releases
and pinned research semantics. Ordinary Advances do not full-replay from
Tracking Origin; only ADR-0107's correction Generation does.

V1 verifies this invariant through historical session-by-session replay tests
and explicit equivalence verification. An ordinary successful daily Advance
does not also run a full batch replay, so the correctness contract does not
turn every post-close update into a full-history computation. A detected
mismatch is a failed equivalence verification and may not be accepted as
"close enough" under a numeric tolerance.
