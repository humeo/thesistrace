# 16 — Author Alpha with authoritative fields and operators

**What to build:** Let a user construct and reopen a normalized Alpha expression
from Data-owned fields and Kernel-owned operators without duplicating catalogs
in the Web.

**Blocked by:** 04, 10, 15.

**Status:** ready-for-agent

- [ ] Authoring options combine Data's canonical authorable fields and the
  Kernel operator catalog through the Definitions module.
- [ ] The Web stores and submits stable field and operator IDs rather than a
  formula string or a hardcoded second catalog.
- [ ] Editable content is limited to optional name, optional hypothesis, Alpha,
  Universe, neutralization, holdings count, and rebalance interval.
- [ ] Dataset Release, field bindings, Strategy kind, initial cash, execution,
  costs, risk-free rate, numeric contract, and semantic versions are not
  editable.
- [ ] Saving and reopening reproduces the authored tree without changing its
  semantics.

**How to verify:**

- Run `uv run pytest -q tests/kernel tests/integration tests/acceptance` and
  confirm authoring options originate from Data and Kernel.
- Run `bun run --cwd web typecheck` and `bun run --cwd web test:e2e`; create and
  reopen an expression using visible field and operator controls.

## Comments
