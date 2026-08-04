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

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/kernel \
  tests/integration \
  tests/acceptance/test_core_definition_authoring.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:core
./scripts/core-test-runtime down
```

The backend test must prove authoring options are composed from Data-owned
fields and Kernel-owned operators. The browser must save and reopen the same
stable-ID expression tree through visible authoring controls.

## Comments
