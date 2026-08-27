# 02 — Hard-cut Strategy execution to Strategy Comparison

**What to build:** Execute and persist only Strategy facts. Persist the existing
list `key_metrics.annualized_excess_return` once at successful ResearchRun
finalization, and assemble Detail comparison from the Benchmark Snapshot.

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] Row, columnar, continuation, retry, Terminal Strategy State, Tracking Origin, Checkpoint, and immutable Result contain no benchmark calculation or state.
- [ ] Immutable Strategy facts include first investable Entry Open, Initial Cash, daily Net NAV, and Terminal coordinate.
- [ ] Successful finalization persists the existing annualized excess key metric; Snapshot unavailability stores `null` without failing the Run.
- [ ] ResearchRun and DailyTrack Detail return the same available/unavailable Strategy Comparison union.
- [ ] Strategy growth uses Initial Cash, Benchmark uses Entry Open, and Net Excess NAV is their ratio with 252-session annualization over the same interval.
- [ ] DailyTrack permanently uses its seed Entry Open and Initial Cash even for a bounded 504-observation response.
- [ ] Snapshot unavailability affects only comparison and invokes no old, carried, alternate, or remote fallback.
- [ ] ResearchRun, Batch, continuation, retry, and DailyTrack equivalence tests pass under the hard cut.
