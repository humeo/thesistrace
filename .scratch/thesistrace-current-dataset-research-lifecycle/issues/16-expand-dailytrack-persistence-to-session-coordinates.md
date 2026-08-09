# 16 — Expand DailyTrack persistence to session coordinates

**What to build:** Add the session-coordinate persistence needed for
Head-based DailyTrack progression beside the existing Release-keyed contract,
so later tickets can migrate activation, catch-up, recovery, and caches without
breaking the repository mid-refactor.

**Blocked by:** 07 — Select and protect one Dataset Head atomically.

**Status:** complete

- [x] Additive durable state can represent Tracking Origin session, current successful Checkpoint session, and a strictly later target session range without a Dataset Release predecessor coordinate.
- [x] New Track, Progression, Attempt, and Checkpoint values round-trip through real PostgreSQL commit and runtime reopen with exact session boundaries, status, terminal account state, and internal Generation audit metadata.
- [x] Persistence rejects non-advancing, reversed, gapped, or current-Checkpoint-inconsistent coordinates without leaving a partial Progression.
- [x] One target can own several consecutive Research Sessions from one selected Generation rather than forcing one Release or one Progression per session.
- [x] Checkpoint ancestry binds the prior successful Checkpoint or Tracking Origin and boundary session, not a browseable Dataset Release chain.
- [x] Expansion does not invent session coordinates for legacy rows and does not delete or rewrite legacy state; guarded cutover and physical contraction remain separate tickets.
- [x] Migration is repeatable on empty and already-expanded databases and preserves Definitions and unrelated product state on failure.
- [x] No new Generation, Attempt, Checkpoint, manifest, or cache mechanics appear in ordinary DailyTrack public payloads.

Implementation evidence:

- `eb26545 feat(daily-track): expand session coordinate persistence` adds the
  parallel session-coordinate schema, repository, runtime seam, and real
  PostgreSQL commit/reopen acceptance without changing the public Track API.
- `20540c2 fix(daily-track): enforce consistent session snapshots` centralizes
  strict Terminal Strategy State validation and removes duplicated durable
  session/state values in favor of Checkpoint-derived coordinates.
- `1491149 fix(daily-track): close session persistence invariants` makes Track,
  Progression, Attempt, and Checkpoint loading one PostgreSQL statement,
  preserves absent Kernel metric accumulators, binds successful Progressions to
  owned Checkpoints, and rejects contradictory continuation sessions.
- `f5e1ab2 fix(daily-track): serialize unresolved progressions` enforces one
  running or blocked Progression per Track and translates competing work into a
  stable domain conflict without partial persistence.
- The focused real-PostgreSQL suite passed 11 scenarios. The adjacent
  Result/Advance/migration/architecture run passed 108 tests; one unrelated
  local lifecycle signal-forwarding test timed out once and immediately passed
  in isolated reproduction. Ruff and focused Pyright checks passed, and both
  fixed-point review axes reported no material findings.
