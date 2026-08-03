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

The command must pass. The suite compares all 16 normalized operators with
their legacy-string equivalents, compares complete Fixture Alpha Matrix
sessions and checksums, exercises every rejection category, and proves the
catalog is Kernel-owned with no dynamic execution path.

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
- Review fix: normalized Field References now accept only stable IDs such as
  `price.close.adjusted`; the runtime binding to `close_adj` stays outside the
  Kernel expression contract. Legacy strings are parsed into that normalized
  tree and then use the same field, literal, arity, window, and lookback
  validator instead of maintaining a second semantic implementation.
- The normalized validator rejects both non-finite floats and integers too
  large to convert to binary64 with the deterministic
  `NON_FINITE_LITERAL` reason code.
- Review round 2 fix: Data now owns the single stable-ID-to-evaluation-name
  catalog. Both the Fixture adapter and the temporary Alpha compatibility
  boundary consume that source, while the Research Kernel receives bindings
  as input and stays independent of Data.
- Post-review ticket verification: the exact command above passed `63 passed`
  in `79.13s`.
- Final independent review: Standards PASS and Spec PASS after three rounds;
  no actionable finding remained.
- The first repository-wide regression gate exposed one retained legacy
  behavior: a string expression containing both a non-authorable field and an
  invalid window reported only the field error. The compatibility converter
  now accumulates its short-name error while the normalized validator supplies
  the independent window error, so no second window rule was introduced.
  The focused regression plus Definition acceptance passed `5 passed`; the
  ticket command then passed `65 passed` in `63.35s` on the expanded suite.
- Final repository gate: `make check` passed with Ruff clean, `466 passed, 28
  skipped` in Python (`329.17s`), Web typecheck and production build green, and
  the narrow/desktop browser chains passing in `23.2s` and `29.1s`.
