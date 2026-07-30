# 05 — Advance DailyTrack from the bounded Working Cache

**What to build:** Let an active DailyTrack process only Research Sessions
after its current Head, rotate its bounded working state, and expose one new
immutable compact Checkpoint without replaying or retaining complete history.

**Blocked by:** 04 — Seed a bounded Working Cache when activating DailyTrack.

**Status:** resolved

- [x] A one-session Dataset Release causes the Track to calculate only that new Research Session, while a catch-up Release processes only its new sessions in canonical order.
- [x] Each new Alpha calculation reads its complete Canonical input window of at most 252 sessions without copying that lookback history into the Working Cache.
- [x] Pending Alpha remains only until its 1-, 5-, and 20-session Labels mature; stock-level Labels are consumed transiently and discarded after their daily Factor aggregates are produced.
- [x] Normal advancement keeps no more than 21 Pending Alpha partitions and rolls Factor observations to the latest 504 signal sessions across three horizons, or 1,512 rows.
- [x] A successful Checkpoint retains a Factor Summary Snapshot, new Strategy Daily Observations and bounded aggregate deltas, and Terminal Strategy State without Alpha, stock-level Labels, daily Factor history, raw orders, fills, or rejection details.
- [x] The committed Working Cache remains within `2,097,152` exact bytes, and a normal Top3000 Advance replaces only the new Pending Alpha partition, rolling Factor object, and basis rather than rewriting all pending sessions.
- [x] Every immutable Checkpoint object and the matching cache replacement complete before Tracking Head moves; any failure leaves the prior Head, Checkpoint, and target Dataset Release unchanged.
- [x] Duplicate delivery returns the existing successful Advance and Checkpoint, and the current Track API and Web view show the new Head, latest Factor summary, Strategy state, processed sessions, and lag.

## Comments

- Normal Advances now calculate Alpha only for sessions after the current Head.
  The calculation reads the frozen Alpha's bounded Canonical lookback, while the
  cache retains only the final 21 signal-session Alpha partitions.
- Each newly mature 1-, 5-, or 20-session Label is constructed in memory,
  reduced immediately to its daily Factor aggregate, and discarded. The
  rolling Factor cache is pruned to 504 sessions by three horizons and the
  immutable Checkpoint publishes only the current Factor Summary Snapshot.
- Strategy continuation starts from immutable Terminal Strategy State and
  Terminal Positions. Each Advance publishes one delta Parquet object for new
  daily observations, Rebalance aggregates, and execution aggregates, plus a
  new Strategy Summary and Terminal State; the API rebuilds the authoritative
  visible sequence from the Checkpoint chain without recalculation.
- Cache rotation hard-links the 20 retained Pending Alpha payloads, writes only
  the new partition and rolling Factor payload, then atomically replaces the
  namespace basis before Head publication. The Top3000 capacity test verifies
  retained inode and SHA identity and the exact 2 MiB namespace bound.
- A forced cache-commit failure leaves the prior Head, sole Checkpoint, target
  Release, and cache basis unchanged. Duplicate successful delivery reuses the
  same Advance and Checkpoint.
- Verification: full backend suite `55 passed`; focused incremental and failure
  acceptance `2 passed`; full Daily Tracking acceptance `1 passed`; Top3000
  rotation capacity acceptance `1 passed`; `uv run ruff check src`; `bun run
  typecheck`; and `bun run build`.
