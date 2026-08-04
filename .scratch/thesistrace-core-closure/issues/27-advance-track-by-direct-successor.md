# 27 — Advance a DailyTrack by one direct successor

**What to build:** Advance an active DailyTrack from its current Head to exactly
the next Dataset Release through Data, Kernel Advance, Publication, PostgreSQL,
and its product detail.

**Blocked by:** 08, 11, 26.

**Status:** ready-for-agent

**Implementation:** complete

- [x] An active Track discovers work through `Data.next_release(current_head)`;
  Data never calls, schedules, or waits for DailyTracks.
- [x] Only the direct successor of the current Head can become the target.
- [x] Kernel Advance consumes the Tracking Origin or prior immutable state and
  only the required new canonical sessions.
- [x] Shared Publication prepares a complete immutable Checkpoint before one
  PostgreSQL transaction records it and moves the Tracking Head under fence.
- [x] Checkpoint provenance binds the DailyTrack, Tracking Origin or previous
  Head, target Release, calculation contracts, and predecessor relationship
  through the same shared Publication contract used by Data and ResearchRuns.
- [x] Publication, claim, or fence failure leaves Head unchanged and any upload
  invisible.
- [x] The Track/target work identity is unique and a repeated completed target
  cannot create a second visible Checkpoint.
- [x] DailyTrack detail shows the new authoritative Head while Data and other
  resources remain independently usable.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/kernel \
  tests/integration \
  tests/acceptance/test_core_daily_track_advance.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:core
./scripts/core-test-runtime down
```

The tests must use real PostgreSQL and RustFS to create a Track at one seed
Release, publish one direct successor through Data, and let the Core worker
discover and process the target without a manual advance endpoint or control.
They must prove `Data.next_release(current_head)` returns only the direct
successor; Kernel Advance receives the prior immutable state plus only newly
appended canonical sessions; one complete immutable Checkpoint is prepared,
verified, and recorded before the same transaction moves Head under fence; and
provenance binds Track, Origin or prior Head, target Release, contracts, and
predecessor. Publication, claim, and stale-fence failures must leave Head
unchanged and uploaded bytes invisible, while repeated processing cannot create
a second visible Checkpoint for the same Track/target. The browser must publish
the successor from Data and observe the existing stable DailyTrack URL move to
the new authoritative Head automatically while Data and ResearchRun pages remain
usable and no manual Advance control or internal worker/fence object is shown.

## Comments

- Data owns direct-successor lookup and has no DailyTrack dependency. The Core
  worker asks DailyTracks for one eligible progression after Data and
  ResearchRun work; no manual Advance HTTP route or Web control exists.
- DailyTracks owns claim/fence SQL and the unique `(track, target)` progression.
  It restores the Tracking Origin or verified prior Checkpoint, slices only the
  successor's appended canonical sessions, and invokes the shared Kernel
  Advance contract.
- A typed private Checkpoint contains the complete next Kernel state. Shared
  Publication prepares it before one PostgreSQL transaction records Publication
  truth, inserts the Checkpoint, moves current Release/session under fence, and
  completes the progression. Product APIs expose only current Release/session.
- Claim rollback, stale fence, and Publication failure keep the product Head and
  visible Publication unchanged. Provenance binds Track, Origin digest or prior
  Checkpoint, target/predecessor Releases, and calculation contracts.
- The final ticket backend command written above passed `83 passed, 1 warning`
  in `117.58s` against real PostgreSQL and RustFS. The final Core browser command
  passed `12 passed` in `40.1s`; its final `down` removed the containers.
- Independent review passed `Standards: PASS` and `Spec: PASS` with no findings,
  including the ticket-local verification command and acceptance scope.
- The final repository `make check` invocation exited `0`: Ruff passed, Python
  passed `522 passed, 91 skipped, 2 warnings` in `405.87s`, Web typecheck and
  production build passed, and narrow/desktop Playwright passed in `28.8s` and
  `29.3s`.
