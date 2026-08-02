# 36 — Prove Local Cold Restart and Compact Restore

**Parent:** 24 — Deliver Hosted Local Acceptance on 2C4G.

**What to build:** Prove bounded survival and restore of the retained product
witness on the same local node. Exercise real backup and restore formats without
claiming off-node independence or production recovery objectives.

**Blocked by:** 29 — Prove Local Identity, Isolation, and Retained Product Health.

**Status:** ready-for-agent

- [ ] The gate records a coordinated manifest for the staged release, PostgreSQL dump or snapshot, Temporal-visible authoritative references, object/index inventory, hashes, state epoch, and retained product witness before interruption.
- [ ] A bounded cold stop and restart of the same Core Session and exact staged release preserves authoritative product state, idempotency, object visibility, and the retained ResearchRun, result, DailyTrack, Dataset, and equivalence evidence without an implicit reset or rebuild.
- [ ] A compact restore is performed into a separately named gate-owned database and object namespace, never over the source session, and refuses mismatched release, migration, state-epoch, or source-manifest digests.
- [ ] Restored database rows, object hashes, manifests, indexes, Workspace isolation, and supported product reads agree with the coordinated manifest; missing or extra authoritative artifacts fail the gate.
- [ ] Backup, cold-restart, restore, and verification durations plus peak resources are recorded with bounded timeouts and exact failure boundaries.
- [ ] Cleanup removes only the isolated restore target after verification and leaves the source witness available for later gates; a failed cleanup or unexpected source mutation invalidates the session.
- [ ] Evidence explicitly does not claim off-node backup independence, whole-node disaster recovery, a six-hour recovery point, an eight-hour recovery time, or production launch qualification.
