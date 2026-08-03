# 07 — Extract Research Kernel Run

**What to build:** Route one immutable calculation input through the pure
Research Kernel Run seam without changing accepted quantitative results.

**Blocked by:** 04.

**Status:** ready-for-agent

**Implementation:** complete

- [x] Run accepts immutable calculation values and canonical data, not product
  IDs, database transactions, object locations, or request context.
- [x] It begins from the canonical initial state and consumes the fixed Research
  Window.
- [x] Its output matches the characterization baseline exactly for Alpha,
  Labels, Factor, Strategy, numeric rules, ordering, and Benchmark behavior.
- [x] There is no Local/Hosted, batch/incremental, or other product mode flag.
- [x] Kernel imports no PostgreSQL, S3, HTTP, worker, quota, or Hosted code.
- [x] Legacy callers may use the temporary expression compatibility boundary,
  but no second calculation implementation is created.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
uv run pytest -q \
  tests/kernel \
  tests/architecture \
  tests/acceptance/test_bounded_research.py
```

The suite must compare Kernel Run with the complete characterization corpus,
prove its input is a value snapshot with no product or deployment context, and
verify the Kernel package imports no lifecycle or infrastructure module.

## Comments

- TDD red: the Kernel contract fails at collection because `RunInput` and
  `research_kernel.run` do not exist.
- TDD green: `RunInput` freezes a deep value snapshot of exactly 756 canonical
  sessions plus explicit Alpha, Universe, neutralization, Strategy, and cost
  values. It has no identity, request, transaction, object, workspace, or mode
  field.
- `research_kernel.run` starts Strategy from the characterized all-cash state
  and produces the same Alpha Matrix, Labels, Factor Evaluation, Strategy,
  Benchmark, event, and diagnostic values as the accepted corpus. The complete
  equality contract and dependency assertions passed `12 passed` focused.
- The old `calculate_research(canonical, definition)` keeps only its temporary
  input conversion and delegates to Kernel Run; it no longer contains a second
  copy of the calculation pipeline.
- Review round 1 found that the first seam still imported infrastructure
  transitively, exposed a mutable expression object, and left the partitioned
  path on a second calculation engine. Alpha, Factor, Strategy, numeric rules,
  and checksum serialization now live under `research_kernel`; legacy modules
  only forward to that implementation.
- An isolated-process import assertion proves loading Kernel does not load
  PostgreSQL, Publication, object storage, HTTP, or worker dependencies.
- The partitioned loader now materializes canonical input and delegates to the
  same Kernel Run. Its acceptance test compares the complete result by exact
  equality instead of maintaining a second calculation implementation.
- After sealing every `RunInput` collection as canonical bytes or tuples, the
  updated exact command above passed `72 passed` in `100.64s`.
