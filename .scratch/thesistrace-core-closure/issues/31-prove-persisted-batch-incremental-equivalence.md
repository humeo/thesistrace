# 31 — Prove persisted batch-incremental equivalence

**What to build:** Prove that full processing from the Tracking Origin and
incremental processing through persisted Checkpoints produce the same canonical
product result at the same Head.

**Blocked by:** 09, 28, 30.

**Status:** ready-for-agent

- [ ] The comparison uses the same Tracking Origin, immutable research
  semantics, ordered Release sequence, Kernel version, and numeric contract.
- [ ] Factor state, Strategy state, Benchmark state, cumulative values, retained
  observations, and terminal continuation state are canonically identical.
- [ ] The proof covers multiple successor Releases and a cache rebuild between
  progressions.
- [ ] Equality is canonical and exact, not a tolerance-only comparison or a
  latest-Release rolling ResearchRun.
- [ ] A mismatch prevents publication and Head movement and identifies the first
  divergent semantic boundary.
- [ ] This ticket tests persisted integration; it does not introduce a second
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
