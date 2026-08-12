---
status: accepted
---

# Require canonical exact Batch-Incremental Equivalence

Reference execution and incremental DailyTrack execution must produce canonically exact results when they use the same Tracking Origin, pinned contracts, ordered Research Sessions, and Canonical inputs, including identical missingness, state transitions, decimal values, and canonical binary64 serialization. Explicit equivalence verification may compare transient Alpha, Label, daily Factor, order, and fill values, but an ordinary Advance never performs a full reference replay.
