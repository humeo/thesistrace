# 08 — Fence concurrent Working Cache writers

**What to build:** Let retries move between two Compute Workers without
allowing a delayed Worker to overwrite, delete, or resurrect a newer
DailyTrack cache or publish a stale Checkpoint.

**Blocked by:** 07 — Rebuild invalid Working Caches within bounded windows.

**Status:** resolved

- [x] The authoritative execution coordinator grants every cache-writing Attempt a monotonically increasing fencing token for its DailyTrack and target Advance.
- [x] Cache payloads are staged under an Attempt identity, validated and atomically installed before the canonical basis record is atomically replaced last.
- [x] A two-Worker failure test starts two independent Compute Worker processes against the same shared WorkingCacheStore and authoritative coordinator; Worker A pauses after staging, Worker B receives a newer token and completes, and Worker A is then unable to commit, delete, clean up, or recreate the current cache.
- [x] A Worker crash after staging, after payload installation, or before basis replacement leaves either one fully valid cache or content that the next Worker rejects and rebuilds through ticket 07.
- [x] Attempt-scoped temporary payloads are removed after success, failure, stale-token rejection, and restart recovery without counting as committed cache state.
- [x] A stale or stopped-Track token cannot move Tracking Head or publish a Checkpoint even when all immutable payload bytes were prepared successfully.
- [x] Cache concurrency and recovery failures leave the last successful Checkpoint, Head, and active-Track admission accounting unchanged.

## Comments

- `daily_tracks.fencing_token` is authoritative. Claiming any pending or blocked
  Advance atomically increments it and records the granted value on the
  Attempt; gaps from failed attempts are retained rather than reused.
- Activation starts at token 1. Every successful Checkpoint and matching cache
  basis publish the Attempt token, and Head publication rechecks active status,
  current Generation/Head, running Attempt ownership, and equality among the
  coordinator, Attempt, Checkpoint, and cache fencing coordinates.
- Cache payloads are written beneath an Attempt-scoped staging directory.
  Immediately before namespace installation, the store rereads the installed
  basis and rejects any token not newer than it. Replacement keeps the prior
  namespace recoverable until the fully validated staged namespace is ready.
- The two-Worker acceptance uses independent spawned Compute Worker processes.
  Worker A stages with token 2 and pauses; the coordinator expires A, Worker B
  claims token 3 and completes the Advance, cache, and Head; A resumes and is
  rejected when attempting to commit, delete, or recreate the token-3 cache.
- Attempt staging is removed on success, calculation failure, stale-token
  rejection, and bounded recovery. Crash remnants or partial namespaces are
  rejected and rebuilt by ticket 07 without changing immutable Head truth.
- Verification: all Tracking concurrency/recovery/replay acceptance `10
  passed`; full backend suite `61 passed`; `uv run ruff check src tests`.
