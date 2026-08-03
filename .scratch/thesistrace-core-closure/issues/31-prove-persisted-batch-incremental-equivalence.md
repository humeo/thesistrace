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

- Run `uv run pytest -q tests/kernel tests/integration` for the reference and
  persisted incremental paths over the same multi-Release fixture.
- Delete the Working Cache mid-sequence and confirm the final canonical result
  remains byte-for-byte equivalent at the same Head.

## Comments
