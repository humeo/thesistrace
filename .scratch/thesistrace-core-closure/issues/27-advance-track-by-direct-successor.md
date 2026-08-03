# 27 — Advance a DailyTrack by one direct successor

**What to build:** Advance an active DailyTrack from its current Head to exactly
the next Dataset Release through Data, Kernel Advance, Publication, PostgreSQL,
and its product detail.

**Blocked by:** 08, 11, 26.

**Status:** ready-for-agent

- [ ] An active Track discovers work through `Data.next_release(current_head)`;
  Data never calls, schedules, or waits for DailyTracks.
- [ ] Only the direct successor of the current Head can become the target.
- [ ] Kernel Advance consumes the Tracking Origin or prior immutable state and
  only the required new canonical sessions.
- [ ] Shared Publication prepares a complete immutable Checkpoint before one
  PostgreSQL transaction records it and moves the Tracking Head under fence.
- [ ] Checkpoint provenance binds the DailyTrack, Tracking Origin or previous
  Head, target Release, calculation contracts, and predecessor relationship
  through the same shared Publication contract used by Data and ResearchRuns.
- [ ] Publication, claim, or fence failure leaves Head unchanged and any upload
  invisible.
- [ ] The Track/target work identity is unique and a repeated completed target
  cannot create a second visible Checkpoint.
- [ ] DailyTrack detail shows the new authoritative Head while Data and other
  resources remain independently usable.

**How to verify:**

- Run `uv run pytest -q tests/kernel tests/integration tests/acceptance` with a
  seed Release and one direct successor against real PostgreSQL and RustFS.
- Run `bun run --cwd web test:e2e`; publish the successor through Data and
  observe the existing Track move exactly one Head without a manual advance
  control.

## Comments
