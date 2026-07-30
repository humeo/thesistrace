---
status: accepted
---

# Advance Daily Tracking with bounded rebuildable working cache

An active DailyTrack advances only newly available Research Sessions and keeps one latest-only, non-authoritative Working Cache in a shared named-volume WorkingCacheStore, bounded to 21 Pending Alpha sessions, 1,512 Rolling Factor Observation rows, and `2,097,152` exact bytes. A fenced single writer publishes cache replacements atomically against the authoritative basis Tracking Checkpoint, while a missing, corrupt, mismatched, or oversized cache is discarded and rebuilt only across those bounded windows by following the Checkpoint chain's ordered Dataset Release sequence. Stopping a DailyTrack durably fences and schedules idempotent cache deletion, with reconciliation removing orphan namespaces after crashes; every durable Factor Summary Snapshot, Strategy delta, and Terminal Strategy State remains in the immutable Tracking Checkpoint rather than the cache.
