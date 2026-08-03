# 08 — Extract Research Kernel Advance

**What to build:** Advance one immutable prior state through new canonical
Research Sessions using the same calculation implementation as Kernel Run.

**Blocked by:** 07.

**Status:** ready-for-agent

- [ ] Advance consumes only prior immutable state, pinned contracts, and the
  required new canonical sessions.
- [ ] It returns a complete new immutable state without mutating its inputs.
- [ ] Run and Advance share Alpha calculation, Label maturation, Factor
  aggregation, Strategy transitions, numeric rules, and canonical ordering.
- [ ] No separately maintained incremental engine or `mode` branch exists.
- [ ] Advance imports no product lifecycle or infrastructure dependency.

**How to verify:**

- Run `uv run pytest -q tests/kernel tests/architecture` and confirm an Advance
  result matches the characterized state at the same session boundary.
- Review dependency evidence to confirm Run and Advance reach the same shared
  calculation implementation.

## Comments
