# 01 — Run two immutable Research Kinds end to end

**What to build:** Let a researcher run either Factor Evaluation or Strategy
Backtest through the existing ResearchRun lifecycle. A Factor Evaluation stops
after the shared Factor calculation and publishes only its Factor Summary, while
Strategy Backtest preserves the complete existing strategy journey and Result.

**Blocked by:** None — can start immediately

**Status:** complete

- [x] Research Kind has exactly two immutable values, `factor_evaluation` and `strategy_backtest`, and is frozen at ResearchRun admission.
- [x] Factor Evaluation admission accepts the common Research inputs and rejects Holdings Count or Rebalance Sessions.
- [x] Strategy Backtest admission requires the common Research inputs, Holdings Count, and Rebalance Sessions under one discriminated command contract.
- [x] Research Kind participates in admission idempotency, immutable-input identity, provenance, execution-plan binding, Checkpoint validation, and retry validation.
- [x] Both kinds use the same strict FIFO ResearchRun Queue, fixed-role Research Worker, supervised child, Generation Pin, fencing, Publication, and terminal lifecycle.
- [x] The execution branch occurs only after the shared Alpha and Factor work; Factor Evaluation performs no Strategy calculation.
- [x] A successful Factor Evaluation publishes a Result Bundle containing exactly `factor_summary`, with no empty or hidden Strategy objects.
- [x] A successful Strategy Backtest continues to publish exactly the existing Factor Summary, Strategy Summary, Strategy Daily Observations, and Terminal Strategy State.
- [x] Result staging, manifest validation, reading, deletion, and recovery reject missing or unexpected objects according to the frozen Research Kind.
- [x] The public ResearchRun representation includes its frozen Research Kind and returns the correct kind-specific Result shape.
- [x] The authoritative backend rejects Start Tracking for Factor Evaluation and preserves Start Tracking for a successful Strategy Backtest.
- [x] The current Product State schema is hard-cut to the new contract without a migration, compatibility reader, fallback, dual Result schema, or alternate execution route.
- [x] Real PostgreSQL, RustFS, Publication, Worker, and child-process acceptance proves one short Run of each kind succeeds with the expected Result and tracking authority.
- [x] Existing Strategy Backtest calculation and DailyTrack seed behavior remain canonically unchanged.

## Comments

- Parent: Factor Evaluation Research Kind.
- This is the first ticket in the approved fully serial implementation chain.
- Implemented one discriminated admission and persisted aggregate contract, one
  shared Alpha/Factor path, strict kind-specific Checkpoint and Result shapes,
  authoritative tracking rejection, and the current Product State hard cut.
- Review: independent Standards and Spec reviews both passed after closing strict
  SQL JSON typing, frozen-input completeness, Result-union, continuation-shape,
  Factor committed-progress, and legal test-fixture findings.
- Verification: `pnpm test` passed with 523 Python tests and 31 frontend shell
  tests; focused kind/Result/continuation tests passed 28/28; final isolated
  `pnpm test:integration` run `20260819t174935z-10198-0cdb3172` passed 181 tests
  plus the database-restart test and cleaned its PostgreSQL/RustFS resources.

## Plan

1. Add failing contract and real-boundary acceptance tests for the two admission
   variants, frozen Research Kind, kind-specific Result object sets, the Factor
   Evaluation tracking rejection, and unchanged Strategy Backtest tracking.
2. Hard-cut Product State and the immutable Research input to one current
   discriminated Research Kind contract. Make Strategy fields structurally absent
   for Factor Evaluation and required for Strategy Backtest; include Kind in
   idempotency, provenance, execution, Checkpoint, and public representations.
3. Deepen the existing shared Research execution path at its natural Factor
   boundary: finalize and return Factor-only work for Factor Evaluation, otherwise
   continue through the existing Strategy implementation. Do not add another
   executor, Worker role, queue, Publication path, compatibility reader, or schema
   migration.
4. Make Result staging, manifest validation, reading, publication, deletion, and
   public projection require the exact object set selected by the frozen Kind.
5. Reject Factor Evaluation Start Tracking at the authoritative service boundary
   while preserving the existing Strategy Backtest seed and DailyTrack flow.
6. Run focused model, kernel, Result-contract, API, PostgreSQL/RustFS, Worker, and
   child-process tests, followed by the repository fast gate. Record the pre-existing
   parallel timing-test baseline separately rather than treating a diagnostic rerun
   as a pass.
7. Review the complete Ticket 01 diff from its fixed starting commit on independent
   Standards and Spec axes, fix every material finding, rerun affected gates, obtain
   clean re-reviews, check all acceptance criteria, update this tracker, and create
   one Ticket 01 commit.
