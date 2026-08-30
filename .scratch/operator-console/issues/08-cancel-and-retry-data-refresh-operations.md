# 08 — Cancel accepted work and Retry immutably

**What to build:** Let the Operator remove obsolete work before it starts and
create an explicit new attempt from terminal work without changing the history,
identity, or outcome of the original Data Refresh Operation.

**Blocked by:** 07 — Expose unified Dataset Operational Status.

**Status:** complete

- [x] Only an accepted, unclaimed Data Refresh Operation offers Cancel, and its
  confirmation dialog shows kind, target, idempotency key, and effect before
  requesting the current password.
- [x] Cancel competes atomically with Worker claim: exactly one action wins, and a
  running or terminal operation cannot be changed to cancelled.
- [x] Failed and cancelled operations offer Retry; Retry copies the prior target
  but creates a new operation with a new editable idempotency key.
- [x] Retry never reopens, rewrites, or aliases the original receipt, and both old
  and new operations remain independently inspectable.
- [x] Cancel and Retry require Operator Proofs bound to the exact operation,
  action, target, and key; invalid, expired, mismatched, or replayed proofs have
  no operation side effect.
- [x] The UI updates the affected row and global FIFO state without claiming that
  accepted or retried work has been processed or published.
- [x] Real-PostgreSQL integration tests cover cancel-before-claim, claim races,
  invalid states, duplicate requests, immutable Retry, and FIFO preservation.
- [x] A real browser test proves accessible confirmation copy, successful Cancel,
  rejected running Cancel, Retry with a new key, and preserved original detail.

## Implementation Plan

1. **Define immutable cancel and retry domain contracts.** Extend the shared
   Data Refresh service with one atomic Cancel transition from `accepted` to
   `cancelled` and one Retry command that accepts only `failed` or `cancelled`
   source receipts. Perform both under the existing Data lifecycle lock, match
   the exact source key, kind, and canonical target, and make Cancel compete
   with the Worker's conditional `accepted` claim so exactly one transition
   wins. Retry will copy the source target and insert a new `accepted` receipt
   under the caller's distinct key without updating, reopening, or aliasing the
   source row.
2. **Bind password proofs to every mutation fact.** Add strict Auth proof
   operations for `data.refresh.cancel` and `data.refresh.retry`. Hash the exact
   action, source idempotency key, kind, canonical target, and—for Retry—the new
   idempotency key; extend both public confirmation and internal consumption
   schemas and the Core authorizer. Preserve the existing one-minute,
   session-bound, single-use claim/consume behavior so expired, mismatched, and
   replayed proofs fail before either domain command runs.
3. **Expose narrow Operator-only HTTP mutations.** Add strict request and safe
   receipt response models for Cancel and Retry beneath
   `/api/operator/data/refreshes`, validate all supplied identities before proof
   consumption, map unavailable source, invalid lifecycle state, target/key
   conflict, and invalid proof to stable non-success responses, and return the
   actual cancelled source or newly accepted retry without suggesting that
   accepted work has run or published.
4. **Add accessible receipt actions and confirmations.** Offer Cancel only on
   visible `accepted` rows and Retry only on `failed` or `cancelled` rows in the
   unified status table and detail drawer. Use labelled native dialogs that show
   kind, target, source key, action effect, and immutable-history warning before
   the password field; let Retry edit and validate a newly generated key, then
   request the action-specific proof and submit the matching Core mutation.
5. **Reconcile races from server truth.** After every success or lifecycle
   rejection, reload the current status page so the affected receipt,
   latest-per-kind summary, and global FIFO state come from the server; keep the
   original detail inspectable after Retry and describe new work only as
   accepted/queued. Preserve visible-only polling, pagination, focus
   restoration, request cancellation, and ordinary Researcher `404` behavior.
6. **Prove atomicity, immutability, and browser behavior.** Add deterministic
   Auth and Web contract tests; real-PostgreSQL tests for cancel-before-claim,
   simultaneous claim/cancel winners, invalid and duplicate requests,
   failed/cancelled Retry, immutable source rows, new-key conflict, and FIFO
   preservation; and a real Caddy browser flow for confirmation copy,
   successful Cancel, rejected running Cancel, editable-key Retry, and preserved
   original details. Run focused and full host, integration, E2E, and
   production-image gates, complete Standards and Spec review/fix/re-review,
   update this tracker, and commit Ticket 08 alone.

## Verification

- `pnpm test`: Ruff and both typechecks passed; 917 Python tests, 171 Auth
  tests, and 145 Web tests passed on the final product tree. The only warning
  was the existing local-lifecycle `forkpty()` deprecation warning.
- `pnpm test:integration`, Core run
  `20260830t110757z-46405-84c99b71`: 413 primary real-dependency tests passed
  with eight environment-selected tests deselected, all six controlled
  PostgreSQL/RustFS restart phases passed, and the isolated project, network,
  and mutable volumes were removed. The following Auth run passed all 128
  PostgreSQL/process integration tests.
- `pnpm test:e2e`, run `20260830t114310z-82342-31b36fcc`: all 16 production
  Caddy browser tests passed, including exact confirmation copy, successful
  queued Cancel, a rejected running Cancel, editable-key immutable Retry,
  preserved source details, honest FIFO state, proof/password boundaries, and
  ordinary-Researcher action `404` behavior.
- `pnpm test:image-smoke`, Core run
  `20260830t114952z-86508-3871e5d7`, Auth run
  `20260830t115922z-90113-06aa618b`, and Caddy run
  `20260830t115945z-90354-753215c6`: final Backend, Auth, Web, Caddy,
  PostgreSQL, RustFS, and Worker image gates passed, including dependency,
  process, and cold-volume recovery.
- Standards review fixed strict action-receipt target projection, separated a
  missing source conflict from the hidden Operator `404`, made generated Retry
  keys deterministic at second precision, completed the exact route inventory,
  deferred success/access callbacks until local state cleanup, and corrected
  the browser PostgreSQL race helper. Re-review found no remaining locking,
  authorization, response-projection, secret-handling, accessibility, cleanup,
  or `DESIGN.md` findings.
- Spec review: PASS after directly covering failed and cancelled Retry,
  cancel/claim atomicity, duplicate and invalid operations, immutable source
  receipts, FIFO order, single-use exact proofs, server-truth reconciliation,
  safe queued copy, and real-browser Researcher denial. Re-review found no
  remaining acceptance gap.
- `git diff --check`: passed on the final unstaged tree before commit.
