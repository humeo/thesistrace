# 04 — Seed a bounded Working Cache when activating DailyTrack

**What to build:** Let a research author explicitly activate Daily Tracking
from a compact successful Result Bundle, preserving the immutable seed state
while creating one separate, bounded, latest-only Working Cache for incremental
continuation.

**Blocked by:** 03 — Add the compact Result Bundle projection.

**Status:** resolved

- [x] Only a succeeded ResearchRun with a complete compact Result Bundle can create a DailyTrack, and idempotent activation returns the same Track without allocating another cache or admission slot.
- [x] Admission atomically enforces an Active DailyTrack Limit of 10; blocked active Tracks count, stopped Tracks do not, and concurrent activation cannot exceed the limit.
- [x] Generation 0 publishes a predecessor-free Activation Checkpoint that binds the seed Result Bundle and carries Terminal Strategy State without copying Alpha or Label history into authoritative state.
- [x] Activation creates no more than 21 signal-session Pending Alpha partitions ordered by instrument identity and one rolling Factor object containing no more than 1,512 rows.
- [x] The complete committed cache namespace, including its basis and payload metadata, is no greater than `2,097,152` exact bytes under a Top3000 capacity fixture.
- [x] The cache basis binds DailyTrack, Generation, basis Checkpoint and checksum, Definition hash, calculation kernel, Numeric Execution Contract, basis Dataset Release, fencing coordinate, and every current payload identity and size.
- [x] Pending Alpha and rolling Factor cache state are calculated from the seed Dataset Release, frozen Definition, and pinned contracts rather than copied from migration-only Alpha, Label, or Factor result objects.
- [x] The Working Cache is stored separately from the immutable Object Store and Worker-private scratch, is not user-visible or backup-critical truth, and is created only for an activated DailyTrack.
- [x] Until ticket 05 migrates the existing Advance consumer, a hidden migration-only seed reference may remain so the complete suite stays green; it is neither authoritative Activation state nor cache content, gains no new consumer, and ticket 06 removes it.
- [x] Starting from an older successful Run preserves the seed Head and queues ordered catch-up rather than silently jumping to the latest Dataset Release.

## Comments

- Added a separate `working-cache/tracks/<daily_track_id>` namespace with one
  deterministic ZSTD Parquet object per Pending Alpha session, one rolling
  Factor Parquet object, and a checksum-bound basis document. Staging plus
  rename makes the initial namespace publication atomic.
- Activation recalculates the cache from the immutable Dataset Release and
  frozen Definition. Its authoritative Checkpoint references only the eight
  compact Result objects; four legacy objects remain under the explicitly
  temporary `migration_seed_objects` index for ticket 05.
- Admission uses `BEGIN IMMEDIATE` and repeats the idempotency check while
  holding the write lock. A concurrent acceptance test proves that two
  activations competing for the tenth slot yield exactly one active Track and
  one cache; stopped Tracks do not consume the slot.
- Capacity acceptance writes the full Top3000 shape: 21 Pending Alpha
  partitions (63,000 rows) plus 1,512 rolling Factor rows, and asserts the
  complete namespace is no larger than `2,097,152` bytes.
- Verification: full backend suite `53 passed`; focused cache activation tests
  `3 passed`; full Daily Tracking acceptance `1 passed`; `uv run ruff check
  src`; `bun run typecheck`; and `bun run build`.
