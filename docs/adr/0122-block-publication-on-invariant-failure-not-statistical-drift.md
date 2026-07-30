---
status: accepted
---

# Block publication on invariant failure, not statistical drift

Immutable publication is blocked by deterministic correctness-invariant failures, including an explicitly requested release-sequence Batch-Incremental Equivalence check, but statistical drift produces warnings rather than rejection. Failed candidates never move authoritative pointers and leave the previously published artifact available, because market behavior may legitimately change statistics while invariant failure proves an invalid result.
