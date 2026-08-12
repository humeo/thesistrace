# 09 — Delete Research and DailyTracks independently

**What to build:** Give researchers explicit, state-safe deletion for Research and
DailyTrack while preserving an independently tracking portfolio after its seed Research
has been removed.

**Blocked by:** 06 — Run a Draft from the browser and view results

**Status:** ready-for-agent

- [ ] Deleting queued or running Research returns a conflict and never performs cancellation implicitly.
- [ ] Succeeded, failed, and cancelled Research can each be permanently deleted through an explicit confirmed action.
- [ ] Research deletion removes its Attempts, accepted-request record, result metadata, and unreferenced Research-owned artifacts.
- [ ] Research deletion never deletes or mutates a DailyTrack seeded from that Research.
- [ ] A surviving DailyTrack retains its complete Tracking Origin, seed Run ID, continuation state, checkpoints, and results and can continue advancing.
- [ ] DailyTrack detail renders a deleted seed Run ID as provenance text rather than a broken live link.
- [ ] Deleting an active or blocked DailyTrack returns a conflict; the existing explicit Stop action is required first.
- [ ] Deleting a stopped DailyTrack removes Track-owned progressions, Attempts, checkpoints, working cache, receipts, and unreferenced objects only.
- [ ] Research and Track deletion never garbage-collect shared immutable Data generations or objects still referenced by another durable resource.
- [ ] Real PostgreSQL/object-store integration tests cover concurrent delete/cancel/stop races, idempotency, ownership, and reference preservation.
- [ ] Real browser E2E proves seed Research deletion, surviving Track reopen/advance, explicit Stop, and stopped Track deletion.

## Comments

- Research Delete, Track Stop, and Track Delete remain three separate user actions.
