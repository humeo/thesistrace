# 02 — Unify the Series Execution Plan

**What to build:** Make every accepted nested Alpha Expression execute through one
deterministic Series evaluator shared by ResearchRun batch calculation and DailyTrack
incremental advancement.

**Blocked by:** 01 — Publish safe Alpha Catalog and Formula Diagnostics

**Status:** ready-for-agent

- [ ] Every builtin has one self-contained definition covering identifier, typed parameters, result rule, documentation, examples, lookback, missingness, numeric behavior, evaluator, and work estimate.
- [ ] A compiled Alpha Expression becomes a transient postorder Series Execution Plan whose nodes are evaluated once per execution.
- [ ] The evaluator owns scalar broadcasting, alignment, warmup, missing values, invalid logarithms, division by zero, finite-number handling, and established Alpha numeric semantics.
- [ ] ResearchRun batch evaluation and session-by-session DailyTrack evaluation call the same evaluator rather than maintaining separate builtin branches.
- [ ] Fixed-seed nested-expression cases produce canonically exact batch-incremental retained results.
- [ ] Data Series are requested through the Data-owned canonical field interface; the Research Kernel contains no physical row-key or duplicate field allowlist.
- [ ] A committed representative benchmark records compile time, plan size, peak memory, and evaluation time and fixes source, node, depth, lookback, and work ceilings before Run admission is enabled.
- [ ] Boundary and one-over resource tests reject over-budget expressions before expensive evaluation or durable mutation.
- [ ] Existing Strategy, Factor Evaluation, Numeric Execution, and DailyTrack progression semantics remain unchanged.
- [ ] Focused evaluator, builtin-contract, equivalence, architecture, and performance-regression tests pass.

## Comments

- This is the intentional prefactor ticket: it makes the later direct-Run hard cut small enough while exposing one independently verifiable evaluator interface.
