# 02 — Recompose Strategy execution from the shared outcome

**What to build:** Let the ordinary Strategy Backtest consume the validated
Alpha-and-Factor outcome and produce the same complete Strategy Result as today,
while making that upstream outcome safe to consume repeatedly with different
Strategy parameters.

**Blocked by:** 01 — Extract a reusable Alpha-and-Factor execution outcome

**Status:** ready-for-agent

- [ ] Ordinary Strategy Backtest continues from the formal Alpha-and-Factor outcome through the one existing Strategy calculation and terminal-state path.
- [ ] The shared outcome is immutable from the Strategy consumer's perspective, so running one Strategy cannot alter the Factor evidence or a later Strategy calculation.
- [ ] Repeating Strategy calculation from one outcome with different Holdings Count and Rebalance Sessions produces one independently validated Strategy outcome per parameter tuple.
- [ ] The same frozen ordinary Strategy Backtest input produces byte-equivalent Factor Summary, Strategy Summary, Strategy Daily Observations, Terminal Strategy State, and semantic checksums before and after the prefactor.
- [ ] Every ordinary Strategy Result retains its own correct ResearchRun identity and calculation provenance.
- [ ] Changing Strategy parameters cannot alter the shared Factor Summary, while deliberate Holdings Count and Rebalance Sessions changes affect the applicable portfolio path.
- [ ] Row-reference, columnar, bounded-Chunk, and uninterrupted Alpha/Factor/Strategy equivalence remain covered through the new consumer boundary.
- [ ] Strategy validation rejects an outcome with the wrong Generation, frozen scope, compiled Alpha identity, Numeric Execution Contract, or semantic versions.
- [ ] Factor Evaluation still performs no Strategy calculation, and successful Strategy Backtest still retains its ordinary Start Tracking authority.
- [ ] The obsolete fused Strategy entry path is removed; there is no alternate Strategy math, compatibility adapter, fallback, or Batch-only kernel.

## Comments

- Parent: Research Batch Worker.
- Approved Prefactor that preserves ordinary Strategy behavior before Batch orchestration is introduced.
