# 16 — Author Alpha with authoritative fields and operators

**What to build:** Let a user construct and reopen a normalized Alpha expression
from Data-owned fields and Kernel-owned operators without duplicating catalogs
in the Web.

**Blocked by:** 04, 10, 15.

**Status:** complete

**Implementation:** complete

- [x] Authoring options combine Data's canonical authorable fields and the
  Kernel operator catalog through the Definitions module.
- [x] The Web stores and submits stable field and operator IDs rather than a
  formula string or a hardcoded second catalog.
- [x] Editable content is limited to optional name, optional hypothesis, Alpha,
  Universe, neutralization, holdings count, and rebalance interval.
- [x] Dataset Release, field bindings, Strategy kind, initial cash, execution,
  costs, risk-free rate, numeric contract, and semantic versions are not
  editable.
- [x] Saving and reopening reproduces the authored tree without changing its
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

- `DataService.authorable_fields()` exposes Data-owned field definitions while
  keeping Kernel evaluation bindings private. The Core runtime injects that
  provider and `ResearchKernel.operator_catalog()` into Definitions, whose
  `authoring_options()` is the only catalog consumed by the Web.
- The authoring-options response contains stable field IDs, public definitions,
  units, Kernel operator arity/type metadata, Universe and neutralization
  choices, and numeric bounds. It excludes Dataset Release, field bindings,
  strategy kind, cash, execution, costs, risk-free rate, numeric contract, and
  semantic versions.
- The Alpha editor derives every operand control from Kernel `operand_rules`,
  so unary, binary, and window operators share one implementation. The saved
  normalized tree contains only `operator_id`, `field_id`, operands, and numeric
  literals; reload restores those exact values without a formula conversion.
- The ticket backend command passed `81 passed, 1 warning` in `168.34s`. The
  real Core browser command passed `3 passed` in `27.6s`, including the stable-ID
  POST payload and full editor state after reload.
- Independent review passed `Standards: PASS` and `Spec: PASS` with no findings.
  It confirmed the dependency injection boundary, absence of a Web catalog,
  dynamic support for all current Kernel operand shapes, editable-field
  whitelist, and save/reopen coverage.
- The final repository `make check` invocation exited `0`: Ruff passed, Python
  passed `518 passed, 52 skipped, 2 warnings`, Web typecheck/build passed, and
  narrow/desktop Playwright passed in `33.7s` and `31.9s`.
