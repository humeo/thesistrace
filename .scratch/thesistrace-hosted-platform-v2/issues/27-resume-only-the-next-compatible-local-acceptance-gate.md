# 27 — Resume Only the Next Compatible Local Acceptance Gate

**Parent:** 24 — Deliver Hosted Local Acceptance on 2C4G.

**What to build:** Add conservative checkpointing that can resume the next gate
in the canonical sequence when both the inputs and the mutated local state still
match. This is sequential recovery, not a reusable DAG cache.

**Blocked by:** 26 — Run One Local Acceptance Gate without Losing Failure State.

**Status:** ready-for-agent

- [ ] Each acceptance session has a stable run ID, a private manifest, a state epoch created by explicit reset, and an append-only per-gate record containing status, timestamps, input state digest, and output state digest.
- [ ] The compatibility fingerprint covers the exact source/worktree inputs, accepted exclusions, release and image digests, Compose/configuration inputs, runtime topology, runner arguments, state epoch, and prerequisite evidence used by the gate.
- [ ] Resume can select only the next canonical gate after the last successful compatible checkpoint. It cannot arbitrarily reorder gates or reuse an earlier checkpoint after a later gate has mutated shared database, Temporal, volume, or object state.
- [ ] A mismatched input or output state digest, changed release/configuration fingerprint, explicit cleanup, or failed state-integrity probe invalidates that gate and all later stateful evidence with a precise explanation.
- [ ] `--fresh` always creates a new run and state epoch and ignores prior checkpoints; normal phase execution remains available without enabling resume.
- [ ] No access, refresh, bearer, or session token is persisted. If test credentials must be retained, they are acceptance-only, permission-restricted, redacted from evidence and logs, and used to obtain a fresh token at every stateful gate.
- [ ] Tests cover compatible continuation, dirty-worktree changes, allowed exclusions, state mutation, interrupted manifest writes, cleanup invalidation, token redaction, and refusal to resume out of order.
