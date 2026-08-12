# 02 — Unify the Series Execution Plan

**What to build:** Make every accepted nested Alpha Expression execute through one
deterministic Series evaluator shared by ResearchRun batch calculation and DailyTrack
incremental advancement.

**Blocked by:** 01 — Publish safe Alpha Catalog and Formula Diagnostics

**Status:** complete

- [x] Every builtin has one self-contained definition covering identifier, typed parameters, result rule, documentation, examples, lookback, missingness, numeric behavior, evaluator, and work estimate.
- [x] A compiled Alpha Expression becomes a transient postorder Series Execution Plan whose nodes are evaluated once per execution.
- [x] The evaluator owns scalar broadcasting, alignment, warmup, missing values, invalid logarithms, division by zero, finite-number handling, and established Alpha numeric semantics.
- [x] ResearchRun batch evaluation and session-by-session DailyTrack evaluation call the same evaluator rather than maintaining separate builtin branches.
- [x] Fixed-seed nested-expression cases produce canonically exact batch-incremental retained results.
- [x] Data Series are requested through the Data-owned canonical field interface; the Research Kernel contains no physical row-key or duplicate field allowlist.
- [x] A committed representative benchmark records compile time, plan size, peak memory, and evaluation time and fixes source, node, depth, lookback, and work ceilings before Run admission is enabled.
- [x] Boundary and one-over resource tests reject over-budget expressions before expensive evaluation or durable mutation.
- [x] Existing Strategy, Factor Evaluation, Numeric Execution, and DailyTrack progression semantics remain unchanged.
- [x] Focused evaluator, builtin-contract, equivalence, architecture, and performance-regression tests pass.

## Comments

- This is the intentional prefactor ticket: it makes the later direct-Run hard cut small enough while exposing one independently verifiable evaluator interface.
- Implemented one canonical Expression-to-postorder Plan path, one shared matrix evaluator, Data-owned Series reader injection, actual selected-Universe execution, and exact warmup/date/Universe admission work accounting.
- Representative maximum-shape evidence retains `3000 × 5000 = 15,000,000` Series values and records `120,480,054` peak bytes and `3,035.362 ms`; the executable gate fixes the 15m Run-work boundary.
- Verification: `ruff check .`; full Python suite `388 passed, 110 skipped`; `bun run typecheck`; Web shell suite `9 passed`.
- Review: final frozen staged SHA-256 `00264beccb28150418efdf4d416e756f24520a46f33a202931979727e092765f` received both Spec pass and Standards pass after all findings were repaired and re-reviewed.
- Delivery: this tracker transition and implementation are finalized together in the Ticket 02 commit.
