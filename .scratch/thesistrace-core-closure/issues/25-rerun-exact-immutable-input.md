# 25 — Rerun the exact immutable input

**What to build:** Let a user create a new ResearchRun from the selected Run's
exact immutable input and Dataset Release.

**Blocked by:** 11, 20.

**Status:** ready-for-agent

- [ ] Rerun always creates a new ResearchRun ID and leaves the selected Run
  unchanged.
- [ ] The new Run copies exactly the original immutable input and Dataset
  Release, including field bindings and fixed calculation contracts.
- [ ] Current Definition edits and a newer latest Release have no effect on the
  new Run.
- [ ] Matching request replay returns the same new Run; different input with the
  same request ID conflicts.
- [ ] A structurally malformed Rerun request creates no action receipt.
- [ ] The new Run enters the ordinary queued, execution, Publication, and
  terminal lifecycle.
- [ ] The Web navigates to the new stable Run URL and preserves provenance to
  the selected original Run without presenting a comparison feature.

**How to verify:**

- Run `uv run pytest -q tests/integration tests/acceptance` after editing the
  Definition and publishing a newer Release; compare the original and rerun
  immutable inputs and Release IDs for exact equality.
- Run `bun run --cwd web test:e2e` and confirm Rerun creates a different Run ID
  while the original remains unchanged.

## Comments
