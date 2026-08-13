# 09 — Delete Research and DailyTracks independently

**What to build:** Give researchers explicit, state-safe deletion for Research and
DailyTrack while preserving an independently tracking portfolio after its seed Research
has been removed.

**Blocked by:** 06 — Run a Draft from the browser and view results

**Status:** complete

- [x] Deleting queued or running Research returns a conflict and never performs cancellation implicitly.
- [x] Succeeded, failed, and cancelled Research can each be permanently deleted through an explicit confirmed action.
- [x] Research deletion removes its Attempts, accepted-request record, result metadata, and unreferenced Research-owned artifacts.
- [x] Research deletion never deletes or mutates a DailyTrack seeded from that Research.
- [x] A surviving DailyTrack retains its complete Tracking Origin, seed Run ID, continuation state, checkpoints, and results and can continue advancing.
- [x] DailyTrack detail renders a deleted seed Run ID as provenance text rather than a broken live link.
- [x] Deleting an active or blocked DailyTrack returns a conflict; the existing explicit Stop action is required first.
- [x] Deleting a stopped DailyTrack removes Track-owned progressions, Attempts, checkpoints, working cache, receipts, and unreferenced objects only.
- [x] Research and Track deletion never garbage-collect shared immutable Data generations or objects still referenced by another durable resource.
- [x] Real PostgreSQL/object-store integration tests cover concurrent delete/cancel/stop races, idempotency, ownership, and reference preservation.
- [x] Real browser E2E proves seed Research deletion, surviving Track reopen/advance, explicit Stop, and stopped Track deletion.

## Comments

- Research Delete, Track Stop, and Track Delete remain three separate user actions.
- Fixed implementation review SHA: `a84b45eddad1906884068c8af3b701e4ff2067d12c46669b218a6f55019ffde5`; Standards and Spec both passed.
- Verification: local `bun run test` passed 378 backend and 25 frontend tests; isolated real integration run `20260812t193547z-2307-b73337ca` passed 117/117 plus database restart 1/1 with cleanup 0; browser E2E run `20260812t192927z-99596-2d1ce6d9` passed 2/2 with cleanup 0.
