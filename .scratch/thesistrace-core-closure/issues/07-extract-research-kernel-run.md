# 07 — Extract Research Kernel Run

**What to build:** Route one immutable calculation input through the pure
Research Kernel Run seam without changing accepted quantitative results.

**Blocked by:** 04.

**Status:** ready-for-agent

- [ ] Run accepts immutable calculation values and canonical data, not product
  IDs, database transactions, object locations, or request context.
- [ ] It begins from the canonical initial state and consumes the fixed Research
  Window.
- [ ] Its output matches the characterization baseline exactly for Alpha,
  Labels, Factor, Strategy, numeric rules, ordering, and Benchmark behavior.
- [ ] There is no Local/Hosted, batch/incremental, or other product mode flag.
- [ ] Kernel imports no PostgreSQL, S3, HTTP, worker, quota, or Hosted code.
- [ ] Legacy callers may use the temporary expression compatibility boundary,
  but no second calculation implementation is created.

**How to verify:**

- Run `uv run pytest -q tests/kernel tests/architecture` and compare Kernel Run
  outputs with the characterization corpus.
- Inspect dependency evidence and confirm the Kernel can execute with no product
  lifecycle or infrastructure process available.

## Comments
