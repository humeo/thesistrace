---
status: accepted
---

# Publish one immutable Tracking Checkpoint per Advance

Each idempotent DailyTrack Advance atomically publishes one immutable Tracking Checkpoint that binds its predecessor, target Dataset Release, pinned contracts, bounded Factor Summary Snapshot, retained Strategy delta, and Terminal Strategy State. The Tracking Head moves only after complete publication succeeds, while Alpha Values, stock-level Labels, daily Factor observations, and raw execution events remain transient.
