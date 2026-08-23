# 05 — Verify the current-schema Production Image journey

**What to build:** Prove that the final Production Image can operate both Research
Kinds across restart and local Product State reset while preserving the already
downloaded Canonical Data and exposing only current-schema product truth.

**Blocked by:** 04 — Prove Factor Summary scientific equivalence

**Status:** complete

## Plan

1. Extend the existing final-image smoke as one current-schema public journey,
   preserving its real HTTP, PostgreSQL, RustFS, fixed-role Worker, supervised
   child, Publication, restart, transient retry, Tracking, and Product State
   reset boundaries rather than adding a second smoke harness.
2. Admit and complete one Factor Evaluation and one Strategy Backtest through
   HTTP; validate their exact kind-specific public Result shapes and durable
   Publication object sets, reject Factor Start Tracking, and advance a real
   Strategy-seeded DailyTrack.
3. Exercise long Factor Evaluation Worker-loss recovery and confirmed
   cancellation in the Production Image, then prove the recovered Result has no
   partial or Strategy objects, no stale winner, and no leaked Generation Pin.
4. Persist and compare kind, Result, manifest, Attempt, Checkpoint, and Tracking
   evidence across application, both role-specific Worker, and PostgreSQL
   restart under the one current schema.
5. Drive the ordinary Product State reset boundary, prove all Product resources
   and RustFS Product objects are removed, prove stale browser references return
   404, and prove the exact mounted Dataset Head and immutable Canonical objects
   reopen offline without a Tushare token.
6. Save one structured final-image evidence artifact with image identity and all
   lifecycle assertions; run focused smoke/unit gates and the complete
   Production Image command, then independent Standards and Spec reviews, fix
   and re-review every material finding, mark the ticket complete, and create
   one Ticket 05 commit.

- [x] The final Production Image admits and completes a Factor Evaluation and a Strategy Backtest through real HTTP, PostgreSQL, RustFS, role-specific Research Worker, supervised child, and Publication boundaries.
- [x] Production smoke verifies the exact kind-specific Result object sets and public detail representations rather than relying on internal branch assertions.
- [x] Factor Evaluation Start Tracking is rejected authoritatively, while the successful Strategy Backtest starts and advances a real DailyTrack.
- [x] Production smoke exercises Factor Evaluation cancellation and Worker-loss recovery without a partial Result, stale publication, or leaked Generation Pin.
- [x] Application, Research Worker, Tracking Worker, and PostgreSQL restart preserve admitted Research Kind, Checkpoints, current Results, manifests, and valid tracking state.
- [x] The ordinary development Product State reset removes obsolete ResearchRuns, Attempts, Checkpoints, Results, DailyTracks, receipts, and RustFS Product objects.
- [x] Product State reset preserves every immutable Canonical Data object and the exact Dataset Head and reopens them without a Tushare token or public network access.
- [x] Browser references to removed Product resources become stale local references rather than being migrated or reinterpreted.
- [x] Startup and Result reads fail closed on an incompatible Product State contract; no compatibility reader, migration, fallback, dual schema, V2 resource, or alternate executor is introduced.
- [x] Structured smoke evidence records image identity, Research Kind, attempt and child lifecycle, Chunk commits, Result manifest, restart, reset, Dataset Head identity, and cleanup.
- [x] The final-image journey is locally reproducible with one documented command and saves actionable diagnostics on failure.

## Comments

- Extended the one existing final-image smoke instead of adding another harness.
  It now completes both Research Kinds through HTTP, PostgreSQL, the fixed-role
  Research Worker, supervised child, RustFS Publication, and exact public and
  durable kind-specific Result shapes.
- The Factor journey proves authoritative Start Tracking rejection, Worker-loss
  resume from a private Checkpoint, two-Attempt recovery, confirmed cancellation,
  no partial or Strategy Result objects, and no leaked Generation Pin. The
  Strategy journey starts and advances real DailyTracks, including transient
  and explicit Retry and confirmed Stop.
- Application, both role Workers, and PostgreSQL restart preserve exact public
  Results, manifests, Research Kind, Checkpoints, and Tracking state. Structured
  Worker logs are parsed as JSON and validate each lifecycle event envelope,
  both kinds, Chunk commits, child exits, and Factor Checkpoint resume.
- Before Product State reset, the Research Worker is stopped and the test proves
  that the same active Factor execution still owns at least one exact Checkpoint
  and one Generation Pin. Reset then removes every Product PostgreSQL row and
  RustFS object, makes all captured Run/Track references return 404, and reopens
  the exact latest Dataset Head with the full Canonical directory hash unchanged
  and no Tushare token on an internal-only network.
- Production Image evidence run `20260819t201037z-5850-4376ba1c` passed every
  phase and recorded image identity, 100 validated lifecycle events, 13 active
  Checkpoints immediately before reset, Product State zero after reset, and
  exact Canonical identity preservation.
- Verification: `pnpm test` passed 523 Python tests, TypeScript type checking,
  and 37 frontend tests. Isolated integration run
  `20260819t201417z-8248-2b3a692a` passed 195 ordinary tests plus the dedicated
  PostgreSQL restart test. Independent Standards/Test Ruler and Spec reviews
  both passed after their material findings were fixed and re-reviewed.
