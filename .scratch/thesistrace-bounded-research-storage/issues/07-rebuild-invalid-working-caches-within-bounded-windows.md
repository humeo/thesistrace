# 07 — Rebuild invalid Working Caches within bounded windows

**What to build:** Let Daily Tracking recover automatically when its
non-authoritative Working Cache is missing, corrupt, incompatible, or
oversized, rebuilding only the bounded continuation windows from immutable
truth.

**Blocked by:** 05 — Advance DailyTrack from the bounded Working Cache; 06 —
Contract to the one-MiB Result Bundle.

**Status:** ready-for-agent

- [ ] A missing basis, missing payload, wrong payload checksum, or partially installed cache is rejected and discarded before use.
- [ ] A wrong Track, Generation, basis Checkpoint, Definition hash, Dataset Release, calculation kernel, Numeric Execution Contract, or fencing coordinate is rejected rather than reused.
- [ ] A cache with more than 21 Pending Alpha sessions, more than 1,512 rolling Factor rows, or more than `2,097,152` committed bytes is rejected.
- [ ] Recovery reconstructs at most the Pending Alpha and latest-504-session Factor windows by following the Activation and Checkpoint chain's exact ordered Dataset Release sequence.
- [ ] Reconstruction uses compact Activation and Checkpoint truth, frozen semantics, and Canonical Dataset Releases only; it cannot read any migration-only compatibility object removed by ticket 06.
- [ ] Recovery never replays the complete Tracking history or changes previously published Factor summaries, Strategy observations, account state, or pending Strategy decisions.
- [ ] A rebuilt cache produces canonically exact retained results and the same next Checkpoint as a Track advanced from an intact valid cache.
- [ ] Worker restart or complete cache-directory loss affects only recovery latency; immutable Checkpoints and the current Head remain sufficient product truth.
- [ ] If bounded reconstruction or cache validation fails, the Attempt is retryable or blocked and Tracking Head remains at the last successful Checkpoint.
