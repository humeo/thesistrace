# 04 — Expand the normalized Alpha expression contract

**What to build:** Add the stable `field_id` and `operator_id` expression tree
beside the old string input so callers can migrate without changing accepted
Alpha semantics.

**Blocked by:** 02.

**Status:** ready-for-agent

- [ ] The normalized tree supports only canonical field references, numeric
  literals, and the closed V1 operator set.
- [ ] The Kernel-owned operator catalog exposes stable IDs, arity, operand
  rules, rolling bounds, and one semantic version.
- [ ] Unknown fields or operators, invalid arity, incompatible operands, and
  rolling values outside 1 through 252 are rejected deterministically.
- [ ] Existing string expressions enter through one explicitly temporary
  compatibility boundary and produce the same characterized result.
- [ ] No Python, SQL evaluation, user-defined function, or runtime plugin
  capability is introduced.

**How to verify:**

- Run `uv run pytest -q tests/kernel tests/architecture` and confirm normalized
  and compatible legacy inputs share the same accepted outputs.
- Confirm invalid tree cases are rejected before calculation and the catalog is
  produced by the Kernel rather than duplicated by a caller.

## Comments
