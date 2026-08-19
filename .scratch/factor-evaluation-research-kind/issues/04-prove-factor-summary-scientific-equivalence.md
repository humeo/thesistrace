# 04 — Prove Factor Summary scientific equivalence

**What to build:** Make Factor Evaluation a scientifically trustworthy outcome by
proving that it reports the same Factor evidence as Strategy Backtest for the same
frozen inputs, including missing evidence, changing Universes, retained diagnostics,
and Chunk boundaries.

**Blocked by:** 03 — Resume and cancel long Factor Evaluation safely

**Status:** ready-for-agent

- [ ] The Factor Summary retains fixed Forward Return Label horizons of 1, 5, and 20 Research Sessions.
- [ ] Every Horizon retains mean Rank IC, Rank ICIR, mean IC, ICIR, Rank IC valid-session Coverage, and IC valid-session Coverage under the current scientific definitions.
- [ ] Existing Five-Quantile Return and Top-Bottom Return calculations, Coverage, and checksums remain in the authoritative Factor Summary.
- [ ] The primary Factor Evaluation view emphasizes only Rank IC, Rank ICIR, IC, ICIR, and Coverage while retained diagnostics remain available to the Result contract.
- [ ] Insufficient valid samples produce null metrics and zero valid-session counts without failing an otherwise valid ResearchRun or fabricating numeric zero.
- [ ] Daily Factor observations, Alpha Values, and stock-level Forward Return Labels remain transient and are not added to the Result Bundle.
- [ ] Identical Formula, resolved Research Period, Universe, Neutralization, field bindings, calculation contracts, and Data Generation produce byte-equivalent `factor_summary` content for Factor Evaluation and Strategy Backtest.
- [ ] Strategy parameters and Strategy outcomes cannot alter the shared Factor calculation or Factor Summary.
- [ ] Chunked and uninterrupted Factor calculation are canonically equivalent across dynamic Universe membership, absent values, rolling operators, cross-sectional ranks, decimal inputs, and every Chunk boundary.
- [ ] Factor-only retry from a private Checkpoint is equivalent to uninterrupted Factor Evaluation and does not duplicate or omit matured Forward Return Labels.
- [ ] Result validation covers binary64 and decimal canonicalization, per-Horizon checksums, retained diagnostics, and public Result serialization rather than only comparing four displayed numbers.
- [ ] A complete public acceptance scenario admits both Research Kinds against the same frozen Generation and compares their published Factor Summaries exactly.
- [ ] Existing Strategy ledger, costs, Benchmark, holdings, rebalance, NAV, and terminal-state reference tests remain unchanged and passing.
