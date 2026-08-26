# Refresh market data through a private operator overlap merge

Only the private Data Operator may build a Market Refresh by merging a bounded overlap and newly completed sessions, recomputing affected derivatives, validating the complete candidate, and atomically moving Dataset Head. Ordinary absence preserves accepted overlap values, governing evidence overrides contradictions, and any incomplete candidate leaves the current Head unchanged without fallback or user-facing correction history.
