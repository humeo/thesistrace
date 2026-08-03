# 08 — Extract Research Kernel Advance

**What to build:** Advance one immutable prior state through new canonical
Research Sessions using the same calculation implementation as Kernel Run.

**Blocked by:** 07.

**Status:** ready-for-agent

**Implementation:** complete

- [x] Advance consumes only prior immutable state, pinned contracts, and the
  required new canonical sessions.
- [x] It returns a complete new immutable state without mutating its inputs.
- [x] Run and Advance share Alpha calculation, Label maturation, Factor
  aggregation, Strategy transitions, numeric rules, and canonical ordering.
- [x] No separately maintained incremental engine or `mode` branch exists.
- [x] Advance imports no product lifecycle or infrastructure dependency.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
uv run pytest -q tests/kernel tests/architecture
```

The suite must compare Advance with the characterized state at the same session
boundary, prove immutable input/output snapshots, and verify Run and Advance
reach the same infrastructure-free calculation implementation.

## Comments

- TDD red: the new contract test failed at collection because `AdvanceInput`
  and `research_kernel.advance` did not exist.
- `KernelState` seals the pinned Run input and complete calculation output as
  immutable values. `AdvanceInput` seals the supplied new-session delta as
  canonical bytes, so later caller mutation cannot change the transition.
- Review round 1 rejected the first implementation because it appended the
  delta and replayed all prior history through `initial_state`. That path and
  the extra public state-builder entry point were removed.
- Run now returns its internal continuous Tracking seed with the ordinary Run
  artifacts. Advance evaluates Alpha only over the required lookback plus new
  sessions, recalculates only new or newly matured Labels, aggregates Factor
  from retained Label state, and invokes Strategy with the prior complete
  continuation state. All steps use the same Kernel functions as Run.
- The characterized 757-session case compares the complete incremental output
  against an explicit full-boundary test oracle, proves Alpha saw 21 sessions
  for a 20-session lookback, proves each Label horizon recalculated only two
  affected signals, and proves Strategy continued `504 -> 505` daily states.
  The 756-session prior state remains unchanged.
- Advance rejects replacement of pinned static contracts instead of
  retroactively changing prior calculation history.
- The updated exact command above passed `75 passed` in `81.21s`.
