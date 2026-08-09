# 16 — Expand DailyTrack persistence to session coordinates

**What to build:** Add the session-coordinate persistence needed for
Head-based DailyTrack progression beside the existing Release-keyed contract,
so later tickets can migrate activation, catch-up, recovery, and caches without
breaking the repository mid-refactor.

**Blocked by:** 07 — Select and protect one Dataset Head atomically.

**Status:** ready-for-agent

- [ ] Additive durable state can represent Tracking Origin session, current successful Checkpoint session, and a strictly later target session range without a Dataset Release predecessor coordinate.
- [ ] New Track, Progression, Attempt, and Checkpoint values round-trip through real PostgreSQL commit and runtime reopen with exact session boundaries, status, terminal account state, and internal Generation audit metadata.
- [ ] Persistence rejects non-advancing, reversed, gapped, or current-Checkpoint-inconsistent coordinates without leaving a partial Progression.
- [ ] One target can own several consecutive Research Sessions from one selected Generation rather than forcing one Release or one Progression per session.
- [ ] Checkpoint ancestry binds the prior successful Checkpoint or Tracking Origin and boundary session, not a browseable Dataset Release chain.
- [ ] Expansion does not invent session coordinates for legacy rows and does not delete or rewrite legacy state; guarded cutover and physical contraction remain separate tickets.
- [ ] Migration is repeatable on empty and already-expanded databases and preserves Definitions and unrelated product state on failure.
- [ ] No new Generation, Attempt, Checkpoint, manifest, or cache mechanics appear in ordinary DailyTrack public payloads.
