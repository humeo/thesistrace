# 20 — Collect retired Data Generations safely

**What to build:** Let a Data Operator explicitly collect retired market-data
Generations and unreferenced objects without deleting the current Head,
in-flight inputs, shared objects, or any durable ResearchRun and DailyTrack
result state.

**Blocked by:** 11 — Recover and fence failed or concurrent Refresh work; 14 — Execute each Attempt against its start-time Head; 18 — Recover DailyTrack without duplicate or partial history.

**Status:** ready-for-agent

- [ ] Garbage collection is an explicit private Data Operator command and never runs as a startup, Refresh, or ordinary Worker side effect.
- [ ] The current Head, every nonterminal Run or Tracking Advance pin, and every candidate owned by nonterminal work are always retained.
- [ ] Completed Result, Checkpoint, and provenance records are not input-data retention roots; their retired Generation may be collected while those outputs remain readable.
- [ ] A Physical Data Object is deleted only when no retained Generation references it; content-addressed objects shared with any retained Generation remain intact.
- [ ] Releasing a terminal pin or completing a candidate operation makes the former temporary root eligible on a later collection, and repeated collection converges safely to no-op.
- [ ] Attempt start, Head movement, pin release, and collection races all use the same Data Lifecycle fence and cannot leave a Head or active pin pointing to a missing Generation.
- [ ] If the authoritative root set or any retained manifest cannot be fully validated, that collection deletes zero objects; if deletion has already begun and an object operation fails, progress is recorded and an idempotent retry converges without widening the prevalidated deletion set.
- [ ] Integration tests use real PostgreSQL, RustFS, and a temporary mounted store and reopen completed Run and Track state after the referenced input Generation is gone.
