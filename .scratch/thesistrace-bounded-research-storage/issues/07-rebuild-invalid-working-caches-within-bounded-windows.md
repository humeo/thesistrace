# 07 — Rebuild invalid Working Caches within bounded windows

**What to build:** Let Daily Tracking recover automatically when its
non-authoritative Working Cache is missing, corrupt, incompatible, or
oversized, rebuilding only the bounded continuation windows from immutable
truth.

**Blocked by:** 05 — Advance DailyTrack from the bounded Working Cache; 06 —
Contract to the one-MiB Result Bundle.

**Status:** resolved

- [x] A missing basis, missing payload, wrong payload checksum, or partially installed cache is rejected and discarded before use.
- [x] A wrong Track, Generation, basis Checkpoint, Definition hash, Dataset Release, calculation kernel, Numeric Execution Contract, or fencing coordinate is rejected rather than reused.
- [x] A cache with more than 21 Pending Alpha sessions, more than 1,512 rolling Factor rows, or more than `2,097,152` committed bytes is rejected.
- [x] Recovery reconstructs at most the Pending Alpha and latest-504-session Factor windows by following the Activation and Checkpoint chain's exact ordered Dataset Release sequence.
- [x] Reconstruction uses compact Activation and Checkpoint truth, frozen semantics, and Canonical Dataset Releases only; it cannot read any migration-only compatibility object removed by ticket 06.
- [x] Recovery never replays the complete Tracking history or changes previously published Factor summaries, Strategy observations, account state, or pending Strategy decisions.
- [x] A rebuilt cache produces canonically exact retained results and the same next Checkpoint as a Track advanced from an intact valid cache.
- [x] Worker restart or complete cache-directory loss affects only recovery latency; immutable Checkpoints and the current Head remain sufficient product truth.
- [x] If bounded reconstruction or cache validation fails, the Attempt is retryable or blocked and Tracking Head remains at the last successful Checkpoint.

## Comments

- Working Cache validation now checks all basis coordinates, the fencing
  coordinate, payload existence and SHA/size/schema, row bounds, exact
  namespace membership, and the exact 2 MiB committed-size limit before any
  cache is used.
- Missing basis, corrupt payload, partial installation, extra payload, bound
  violation, or coordinate mismatch causes the namespace and stale staging
  files to be discarded. Rebuild follows and validates the compact Checkpoint
  chain's ordered Dataset Releases before using its current Head Release.
- Rebuild reads at most the latest 504 Factor signal sessions plus the frozen
  Alpha's at-most-252-session Canonical lookback. It persists only the latest
  21 Pending Alpha partitions and 1,512 Factor rows; Strategy observations,
  Terminal State, pending decisions, and prior summaries remain immutable
  Checkpoint truth and are never replayed or rewritten.
- Acceptance destroys one of two otherwise identical Track caches. Its rebuilt
  Track and intact peer publish the same seven next-Checkpoint payload SHAs,
  the same cache payload identities, and both pass the batch equivalence
  oracle.
- Forced bounded-rebuild failure leaves the active Track's prior Head and sole
  Checkpoint unchanged and blocks the Attempt for retry.
- Verification: full backend suite `60 passed`; focused corruption,
  complete-loss equivalence, and failed-rebuild acceptance `3 passed`; `uv run
  ruff check src tests`.
