---
status: accepted
---

# Publish one immutable Tracking Checkpoint per Advance

Each idempotent DailyTrack Advance atomically publishes one immutable Tracking Checkpoint that binds its predecessor, completed session coordinate, Attempt Data Generation provenance, pinned contracts, bounded Factor Summary Snapshot, retained Strategy delta, and Terminal Strategy State. The Tracking Head moves only after complete publication succeeds, while Alpha Values, stock-level Labels, daily Factor observations, and raw execution events remain transient.

ADR-0209 keeps that Tracking Head as the only recovery truth. A failed Attempt
publishes no private execution checkpoint and its next Attempt recalculates the
selected unpublished sessions from this authoritative predecessor. One Advance
publishes its frozen, capacity-planned 1-to-64-session Target; longer catch-up
uses multiple independently atomic Advances. Later Attempts never expand or
shrink that Target.
