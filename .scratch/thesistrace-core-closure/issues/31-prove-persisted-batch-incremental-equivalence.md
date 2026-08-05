# 31 — Prove persisted batch-incremental equivalence

**What to build:** Prove that full processing from the Tracking Origin and
incremental processing through persisted Checkpoints produce the same canonical
product result at the same Head.

**Blocked by:** 09, 28, 30.

**Status:** complete

**Implementation:** complete

- [x] The comparison uses the same Tracking Origin, immutable research
  semantics, ordered Release sequence, Kernel version, and numeric contract.
- [x] Factor state, Strategy state, Benchmark state, cumulative values, retained
  observations, and terminal continuation state are canonically identical.
- [x] The proof covers multiple successor Releases and a cache rebuild between
  progressions.
- [x] Equality is canonical and exact, not a tolerance-only comparison or a
  latest-Release rolling ResearchRun.
- [x] A mismatch prevents publication and Head movement and identifies the first
  divergent semantic boundary.
- [x] This ticket tests persisted integration; it does not introduce a second
  calculation engine or duplicate ticket 09's pure Kernel proof.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/kernel/test_once_chunked_equivalence.py \
  tests/integration \
  tests/acceptance/test_core_daily_track_equivalence.py
./scripts/core-test-runtime down
```

The persisted test must use real PostgreSQL and RustFS. It must start one
DailyTrack from a succeeded seed ResearchRun, publish and process at least three
ordered successor Dataset Releases, delete the worker-local Working Cache
between two progressions, and then replay the same Tracking Origin and exact
recorded Release identities through the single Research Kernel implementation.
At every persisted Checkpoint it must compare canonical Factor state, Strategy
and Benchmark state, cumulative values, retained observations, and terminal
continuation state exactly, including binary64 and Decimal encodings. The final
reference and persisted states must identify the same Head and have identical
canonical evidence bytes. An injected mismatch must report the first stable
semantic path while leaving Publication count, Checkpoint count, Head Release,
and cache bytes unchanged. The proof must not run a latest-Release ResearchRun,
add a second calculation engine, or make ordinary Advance replay full history.

## Comments

- TDD red used the real three-successor Release flow and failed only because
  `DailyTrackService` had no persisted-equivalence verification boundary. The
  initial environment, seed Run, Track activation, three Advances, and cache
  deletion all completed before the expected `AttributeError`.
- Implemented in `1f6cd8e`. Verification takes a read-only snapshot of the
  Tracking Origin, Head, and predecessor-linked Checkpoint rows; rebuilds the
  fixed 756-session seed; and replays the exact recorded Release identities
  through the same Kernel `run` and injected `advance` callable used by normal
  processing. Ordinary Advance remains unchanged and never performs this
  reference replay.
- Every expected Checkpoint uses the DailyTrack-owned product projection and is
  compared to the verified immutable payload with the Kernel-owned canonical
  binary64/Decimal equality implementation. Provenance, Factor Summary,
  Strategy and Benchmark state, cumulative metrics, retained deltas, terminal
  state, continuation digest, Checkpoint session, and final Head are all part of
  the proof evidence.
- Real acceptance publishes three direct successors and deletes the private
  Working Cache after the first progression. A second scenario injects a
  terminal Checkpoint `benchmark_nav` mismatch and receives the exact first
  path while spies reject any Publication prepare/record call; PostgreSQL
  Publication and Checkpoint counts, Head, and cache bytes remain unchanged.
  No HTTP or Web equivalence action was added.
- Independent review passed both Standards and Spec in the first round with no
  findings. The committed focused Kernel plus real acceptance set reported `5
  passed, 1 warning in 113.41s`; architecture separately reported `19 passed`.
- Final verification was run exactly from **How to verify** against isolated
  real PostgreSQL and RustFS and passed: `23 passed, 1 warning in 123.62s`; the
  command block then removed both runtime containers.
- Final repository verification passed with `make check`: Ruff passed; Pytest
  reported `533 passed, 102 skipped, 2 warnings in 588.93s`; Web typecheck and
  production build passed (`1590` modules in `1.07s`); narrow E2E reported `1
  passed in 33.6s`; desktop E2E reported `1 passed in 26.4s`.
