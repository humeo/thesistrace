# 04 — Seed a bounded Working Cache when activating DailyTrack

**What to build:** Let a research author explicitly activate Daily Tracking
from a compact successful Result Bundle, preserving the immutable seed state
while creating one separate, bounded, latest-only Working Cache for incremental
continuation.

**Blocked by:** 03 — Add the compact Result Bundle projection.

**Status:** ready-for-agent

- [ ] Only a succeeded ResearchRun with a complete compact Result Bundle can create a DailyTrack, and idempotent activation returns the same Track without allocating another cache or admission slot.
- [ ] Admission atomically enforces an Active DailyTrack Limit of 10; blocked active Tracks count, stopped Tracks do not, and concurrent activation cannot exceed the limit.
- [ ] Generation 0 publishes a predecessor-free Activation Checkpoint that binds the seed Result Bundle and carries Terminal Strategy State without copying Alpha or Label history into authoritative state.
- [ ] Activation creates no more than 21 signal-session Pending Alpha partitions ordered by instrument identity and one rolling Factor object containing no more than 1,512 rows.
- [ ] The complete committed cache namespace, including its basis and payload metadata, is no greater than `2,097,152` exact bytes under a Top3000 capacity fixture.
- [ ] The cache basis binds DailyTrack, Generation, basis Checkpoint and checksum, Definition hash, calculation kernel, Numeric Execution Contract, basis Dataset Release, fencing coordinate, and every current payload identity and size.
- [ ] Pending Alpha and rolling Factor cache state are calculated from the seed Dataset Release, frozen Definition, and pinned contracts rather than copied from migration-only Alpha, Label, or Factor result objects.
- [ ] The Working Cache is stored separately from the immutable Object Store and Worker-private scratch, is not user-visible or backup-critical truth, and is created only for an activated DailyTrack.
- [ ] Until ticket 05 migrates the existing Advance consumer, a hidden migration-only seed reference may remain so the complete suite stays green; it is neither authoritative Activation state nor cache content, gains no new consumer, and ticket 06 removes it.
- [ ] Starting from an older successful Run preserves the seed Head and queues ordered catch-up rather than silently jumping to the latest Dataset Release.
