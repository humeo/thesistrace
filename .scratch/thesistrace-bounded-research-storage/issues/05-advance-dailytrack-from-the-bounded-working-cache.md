# 05 — Advance DailyTrack from the bounded Working Cache

**What to build:** Let an active DailyTrack process only Research Sessions
after its current Head, rotate its bounded working state, and expose one new
immutable compact Checkpoint without replaying or retaining complete history.

**Blocked by:** 04 — Seed a bounded Working Cache when activating DailyTrack.

**Status:** ready-for-agent

- [ ] A one-session Dataset Release causes the Track to calculate only that new Research Session, while a catch-up Release processes only its new sessions in canonical order.
- [ ] Each new Alpha calculation reads its complete Canonical input window of at most 252 sessions without copying that lookback history into the Working Cache.
- [ ] Pending Alpha remains only until its 1-, 5-, and 20-session Labels mature; stock-level Labels are consumed transiently and discarded after their daily Factor aggregates are produced.
- [ ] Normal advancement keeps no more than 21 Pending Alpha partitions and rolls Factor observations to the latest 504 signal sessions across three horizons, or 1,512 rows.
- [ ] A successful Checkpoint retains a Factor Summary Snapshot, new Strategy Daily Observations and bounded aggregate deltas, and Terminal Strategy State without Alpha, stock-level Labels, daily Factor history, raw orders, fills, or rejection details.
- [ ] The committed Working Cache remains within `2,097,152` exact bytes, and a normal Top3000 Advance replaces only the new Pending Alpha partition, rolling Factor object, and basis rather than rewriting all pending sessions.
- [ ] Every immutable Checkpoint object and the matching cache replacement complete before Tracking Head moves; any failure leaves the prior Head, Checkpoint, and target Dataset Release unchanged.
- [ ] Duplicate delivery returns the existing successful Advance and Checkpoint, and the current Track API and Web view show the new Head, latest Factor summary, Strategy state, processed sessions, and lag.
