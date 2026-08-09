# 04 — Publish variable-length four-value Result Bundles

**What to build:** Publish the existing four durable Result values for any
Research Period length, storing growing daily observations in the production
tabular encoding and enforcing the session-scaled owned-byte budget atomically.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] A successful durable Result contains exactly `factor_summary`, `strategy_summary`, `strategy_daily_observations`, and `terminal_strategy_state` as its four top-level values.
- [ ] Strategy Daily Observations accept any positive Research Period length; no projection or publication rule requires exactly 504 rows.
- [ ] Growing Strategy Daily Observations use the established deterministic partitioned Parquet object contract, while bounded manifests, summaries, and terminal state retain deterministic bounded encodings.
- [ ] Raw Alpha Values, stock-level Labels, daily Factor observations, Strategy Ledger rows, orders, fills, and position history are rejected from durable publication.
- [ ] The complete Result Bundle budget is exactly `ceil(research_period_session_count / 504) * 1,048,576` owned bytes, including its manifest and every required payload.
- [ ] Production byte-budget policy tests prove exact-limit acceptance and limit-plus-one rejection for period lengths 1, 504, 505, 1008, and 1009.
- [ ] A legal under-budget Result publishes and reopens through production serialization and storage; a constructible legal over-budget Result publishes nothing and leaves no partial visible state.
- [ ] Repeated publication preparation of the same Result produces the same canonical object identities and manifest bytes.
