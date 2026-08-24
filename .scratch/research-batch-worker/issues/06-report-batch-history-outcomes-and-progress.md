# 06 — Report truthful Batch history, outcomes, and progress

**What to build:** Give API clients durable, cursor-paginated Research Batch
history and ordered detail with unambiguous aggregate outcomes, monotonic
whole-task progress, and clearly estimated live progress for the current task.

**Blocked by:** 05 — Execute Strategy Sweeps from one shared Alpha and Factor

**Status:** completed

## Implementation plan

1. Hard-cut the public Batch projection into a compact cursor-list Summary and
   an ordered Detail containing kind-specific durable progress, stable timing,
   the current/latest Attempt, live estimated progress, and item outcomes.
2. Persist immutable terminal item outcomes and sanitized diagnostics in Batch
   ownership, plus Attempt-scoped live task snapshots that can reset without
   changing acknowledged task counts.
3. Extend the supervised child protocol with acknowledged task-start messages
   and session counts, then have the supervisor fence and persist each live
   snapshot before forwarding the same observability event.
4. Derive natural aggregate outcomes only from final child outcomes, clear live
   progress on terminal completion, and project Run availability/deletion
   placeholders without embedding ordinary Result Bundles.
5. Add API contract, PostgreSQL integration, restart, cursor, failure-sanitizing,
   monotonic-progress, and no-frontend acceptance; then run independent
   Standards and Spec reviews before the Ticket 06 commit.

- [x] Batch lifecycle exposes queued and running plus terminal succeeded, completed_with_failures, failed, and cancelled outcomes under one current contract.
- [x] Natural completion is succeeded only when every child succeeds, completed_with_failures when successes and failures coexist, and failed when no child succeeds.
- [x] Factor Batch durable progress reports completed and total complete Factor tasks.
- [x] Strategy Sweep durable progress reports the shared Alpha-and-Factor prerequisite status plus completed and total complete Strategy tasks.
- [x] Durable completed-task progress is monotonic and remains authoritative across Worker loss, retry, API restart, and storage reconnection.
- [x] While work is active, detail identifies the current item_key, phase, completed and total Research Sessions when applicable, estimated percentage, elapsed time, remaining-duration estimate when evidence is sufficient, and Attempt number.
- [x] Live percentage and remaining time are explicitly labelled as estimates rather than Results, checkpoints, or completion guarantees.
- [x] Live progress for an incomplete task may reset after a retry, while acknowledged task counts and published outcomes never regress.
- [x] Terminal detail records stable execution timing and the latest Attempt information without retaining a misleading active heartbeat.
- [x] Cursor-paginated listing has deterministic ordering and returns frozen scope, Generation identity, aggregate state, timing, and compact durable progress.
- [x] Detail returns ordered item_key-to-ResearchRun mappings, Run availability, final outcomes, Attempt information, sanitized diagnostics, and any child deletion timestamp.
- [x] Formula and execution failures expose actionable item-aware diagnostics without secrets, credentials, internal object keys, or unsafe traceback details.
- [x] Child Result Bundles remain available only through ordinary ResearchRun detail and are never embedded or duplicated in Batch representations.
- [x] Missing Batch and invalid cursor behavior follow the current public API conventions, and restart preserves all durable history.
- [x] V1 adds no Batch authoring, list, detail, progress, or control UI; the accepted backend HTTP representation is the product boundary.

## Comments

- Parent: Research Batch Worker.
- This ticket makes progress displayable without pretending incomplete work is durably complete.
- Standards review: PASS, P0/P1/P2 = 0/0/0 after re-review. The final fixes
  atomically commit child outcome, diagnostic, and durable progress; close
  Attempt and Item database invariants; and reject PostgreSQL `NULL` truth-value
  gaps with real invalid-write acceptance.
- Spec review: PASS, P0/P1/P2 = 0/0/0 after re-review. Real multi-chunk Factor,
  shared Alpha-and-Factor, and per-Strategy barriers prove live estimates advance
  without prematurely advancing durable task counts.
- Fast gate: Ruff passed and 558 tests passed. Web typecheck passed and all 56
  shell tests passed.
- Isolated PostgreSQL/RustFS integration run
  `20260824t015447z-94394-334607fc`: 217 passed, then the database-restart
  acceptance passed; isolated containers, network, and data volumes were
  cleaned up.
