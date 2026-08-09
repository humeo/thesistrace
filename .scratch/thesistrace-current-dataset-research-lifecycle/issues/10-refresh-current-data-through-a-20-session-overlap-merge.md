# 10 — Refresh current data through a 20-session overlap merge

**What to build:** Let a Data Operator asynchronously Refresh the mounted
current Dataset through a governed overlap merge, publish one completely
validated new Head or successful no-op, and leave no correction product for
ordinary users.

**Blocked by:** 05 — Expand Liquidity only at Dataset Coverage Start; 07 — Select and protect one Dataset Head atomically; 08 — Bootstrap a Head through the private Data Operator.

**Status:** complete

- [x] The private operator command accepts an idempotent Refresh request and returns before Worker completion; private inspection can observe its accepted, running, and terminal product-safe status, while ordinary HTTP has no submission or inspection route.
- [x] The source plan begins at the nineteenth Research Session before current data-through, includes the current final session, and ends at the latest completed Research Session, including every missed new session.
- [x] For an overlap key, a normalized returned value replaces the current value, ordinary source absence preserves it, and explicit governing trading-state, listing, or delisting evidence removes or invalidates conflicting price or turnover facts.
- [x] A new Research Session has no preservation fallback and cannot enter a candidate without all required calendar, instrument, price, adjustment, trading-state, suspension, and price-limit facts.
- [x] Adjustment corrections recompute every dependency-affected Adjusted Research Price; turnover corrections recompute every affected Liquidity Score, Rank, and Universe Membership before validation.
- [x] A valid non-identical candidate finalizes one complete Data Generation and atomically moves Head; a correction-only candidate may move Head without a new session, and an identical candidate completes as a successful no-op without a new Generation.
- [x] Every successful Refresh, including an identical no-op, sets or advances `last_refresh_at`; failures and Bootstrap do not.
- [x] Refresh produces no per-value correction resource, historical diff, user notification, or operator detail in Data Overview; acceptance uses the private command, Worker, real PostgreSQL, a temporary mount, and a deterministic recording source.
