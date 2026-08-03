# 04 — Expand the normalized Alpha expression contract

**What to build:** Add the stable `field_id` and `operator_id` expression tree
beside the old string input so callers can migrate without changing accepted
Alpha semantics.

**Blocked by:** 02.

**Status:** ready-for-agent

**Implementation:** complete

- [x] The normalized tree supports only canonical field references, numeric
  literals, and the closed V1 operator set.
- [x] The Kernel-owned operator catalog exposes stable IDs, arity, operand
  rules, rolling bounds, and one semantic version.
- [x] Unknown fields or operators, invalid arity, incompatible operands, and
  rolling values outside 1 through 252 are rejected deterministically.
- [x] Existing string expressions enter through one explicitly temporary
  compatibility boundary and produce the same characterized result.
- [x] No Python, SQL evaluation, user-defined function, or runtime plugin
  capability is introduced.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
uv run pytest -q tests/kernel tests/architecture
```

The command must pass `60` tests. The suite compares all 16 normalized
operators with their legacy-string equivalents, compares complete Fixture
Alpha Matrix sessions and checksums, exercises every rejection category, and
proves the catalog is Kernel-owned with no dynamic execution path.

## Comments

- Normalized nodes have exactly one of three shapes: `{field_id}`,
  `{literal}`, or `{operator_id, operands}`. Unknown or mixed properties fail
  before calculation.
- The Kernel catalog has semantic version `1.0.0` and is the source for both
  normalized validation and legacy execution's scalar/historical/rolling
  operator groups. Callers do not maintain a second operator list.
- `validate_legacy_alpha` is the single explicitly temporary string-parser
  boundary. Normalized input constructs only the already-characterized AST
  nodes and never calls Python `eval`, `exec`, SQL, import hooks, plugins, or
  user-defined functions.
- TDD red: the catalog reported `pending`, normalized input raised a dict/string
  type error, and all `11` initial contract cases failed at the intended public
  behavior.
- TDD green: all 16 operators match their legacy equivalents exactly; the
  normalized and legacy Fixture matrices have identical sessions, effective
  lookback, and checksum; the final Kernel plus architecture command passed
  `60 passed` in `68.00s` through the exact `uv run` command above.
