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
  against an independent one-shot calculation at the same boundary, proves
  Alpha saw 21 sessions for a 20-session lookback, proves each Label horizon
  recalculated only two affected signals, and proves Strategy only reopened the
  prior terminal boundary before appending the new session. The 756-session
  prior state remains unchanged.
- Review round 2 found that the first incremental version used a second
  continuous Strategy seed instead of the seed Run terminal state. Run now
  creates Track state directly from its Result Strategy; a rebalance-interval-1
  case proves both are exactly equal before Advance.
- Field catalog and calculation semantics remain pinned. Later instruments,
  adjustment anchors, and time-point industry reference snapshots may evolve
  for new calculation without mutating the prior state. Label maturation offset
  selection is owned by Factor rather than repeated in Advance.
- Review round 3 found that a terminal cutoff had made the prior terminal day
  impossible to advance correctly for `rebalance_interval = 1`, and that a
  dictionary subclass hid Track state inside ordinary Result artifacts. Kernel
  state now retains the bounded pre-terminal Strategy continuation, so Advance
  reopens exactly that boundary and still matches a one-shot 757-session Run.
  `RunOutput` is now an explicit immutable value with separate artifact and
  Track-state accessors; the product adapter extracts only the artifacts.
- The exact `How to verify` command above passed `77 passed, 1 warning` in
  `100.12s`.
