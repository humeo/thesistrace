# 08 — Fence concurrent Working Cache writers

**What to build:** Let retries move between two Compute Workers without
allowing a delayed Worker to overwrite, delete, or resurrect a newer
DailyTrack cache or publish a stale Checkpoint.

**Blocked by:** 07 — Rebuild invalid Working Caches within bounded windows.

**Status:** ready-for-agent

- [ ] The authoritative execution coordinator grants every cache-writing Attempt a monotonically increasing fencing token for its DailyTrack and target Advance.
- [ ] Cache payloads are staged under an Attempt identity, validated and atomically installed before the canonical basis record is atomically replaced last.
- [ ] A two-Worker failure test starts two independent Compute Worker processes against the same shared WorkingCacheStore and authoritative coordinator; Worker A pauses after staging, Worker B receives a newer token and completes, and Worker A is then unable to commit, delete, clean up, or recreate the current cache.
- [ ] A Worker crash after staging, after payload installation, or before basis replacement leaves either one fully valid cache or content that the next Worker rejects and rebuilds through ticket 07.
- [ ] Attempt-scoped temporary payloads are removed after success, failure, stale-token rejection, and restart recovery without counting as committed cache state.
- [ ] A stale or stopped-Track token cannot move Tracking Head or publish a Checkpoint even when all immutable payload bytes were prepared successfully.
- [ ] Cache concurrency and recovery failures leave the last successful Checkpoint, Head, and active-Track admission accounting unchanged.
