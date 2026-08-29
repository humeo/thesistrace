# 08 — Cancel accepted work and Retry immutably

**What to build:** Let the Operator remove obsolete work before it starts and
create an explicit new attempt from terminal work without changing the history,
identity, or outcome of the original Data Refresh Operation.

**Blocked by:** 07 — Expose unified Dataset Operational Status.

**Status:** ready-for-agent

- [ ] Only an accepted, unclaimed Data Refresh Operation offers Cancel, and its
  confirmation dialog shows kind, target, idempotency key, and effect before
  requesting the current password.
- [ ] Cancel competes atomically with Worker claim: exactly one action wins, and a
  running or terminal operation cannot be changed to cancelled.
- [ ] Failed and cancelled operations offer Retry; Retry copies the prior target
  but creates a new operation with a new editable idempotency key.
- [ ] Retry never reopens, rewrites, or aliases the original receipt, and both old
  and new operations remain independently inspectable.
- [ ] Cancel and Retry require Operator Proofs bound to the exact operation,
  action, target, and key; invalid, expired, mismatched, or replayed proofs have
  no operation side effect.
- [ ] The UI updates the affected row and global FIFO state without claiming that
  accepted or retried work has been processed or published.
- [ ] Real-PostgreSQL integration tests cover cancel-before-claim, claim races,
  invalid states, duplicate requests, immutable Retry, and FIFO preservation.
- [ ] A real browser test proves accessible confirmation copy, successful Cancel,
  rejected running Cancel, Retry with a new key, and preserved original detail.
