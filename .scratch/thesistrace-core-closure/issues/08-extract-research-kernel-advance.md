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
- Run and Advance both enter `initial_state`; Alpha, Labels, Factor, Strategy,
  numeric rules, Result composition, and fixed Tracking origin therefore have
  one implementation and no mode branch.
- The characterized 757-session case compares the complete Advance output with
  the state produced at the same boundary and verifies the 756-session prior
  state remains unchanged.
- The exact command above passed `74 passed` in `82.63s`.
