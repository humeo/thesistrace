# 04 — Publish variable-length four-value Result Bundles

**What to build:** Publish the existing four durable Result values for any
Research Period length, storing growing daily observations in the production
tabular encoding and enforcing the session-scaled owned-byte budget atomically.

**Blocked by:** None — can start immediately.

**Status:** complete

- [x] A successful durable Result contains exactly `factor_summary`, `strategy_summary`, `strategy_daily_observations`, and `terminal_strategy_state` as its four top-level values.
- [x] Strategy Daily Observations accept any positive Research Period length; no projection or publication rule requires exactly 504 rows.
- [x] Growing Strategy Daily Observations use the established deterministic partitioned Parquet object contract, while bounded manifests, summaries, and terminal state retain deterministic bounded encodings.
- [x] Raw Alpha Values, stock-level Labels, daily Factor observations, Strategy Ledger rows, orders, fills, and position history are rejected from durable publication.
- [x] The complete Result Bundle budget is exactly `ceil(research_period_session_count / 504) * 1,048,576` owned bytes, including its manifest and every required payload.
- [x] Production byte-budget policy tests prove exact-limit acceptance and limit-plus-one rejection for period lengths 1, 504, 505, 1008, and 1009.
- [x] A legal under-budget Result publishes and reopens through production serialization and storage; a constructible legal over-budget Result publishes nothing and leaves no partial visible state.
- [x] Repeated publication preparation of the same Result produces the same canonical object identities and manifest bytes.

## Comments

- Implemented by `2967c0a feat(result): publish variable-length four-value bundles`; stable Parquet partitions and real over-budget publication coverage are in `6dad348 fix(result): partition and validate durable bundles`; strict leaf validation and its centralized Pydantic models are in `8703385 fix(result): validate durable leaf types` and `290836a refactor(result): centralize durable schemas`.
- The complete real PostgreSQL/RustFS integration and acceptance milestone passed `104 passed, 1 warning in 1908.50s`; the final strict-schema Production Image seams passed `4 passed, 1 warning in 283.50s`, covering partitioned publication, successful Run reopen, over-budget atomic failure, and DailyTrack origin loading.
- Final Kernel verification passed `118 passed in 361.05s`; focused strict-schema tests passed `40 passed in 7.53s`; Ruff, format, and diff checks passed.
- Standards and Spec reviews used fixed point `290836a`. After partitioning, actual-byte overflow, strict leaf typing, and schema-centralization fixes, both dimensions ended with zero material findings.
