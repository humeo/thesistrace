# 11 — Publish a later Dataset Release

**What to build:** Publish later canonical sessions as the next immutable
Dataset Release while preserving every earlier Release and its provenance.

**Blocked by:** 10.

**Status:** ready-for-agent

- [ ] Collection starts from the latest successful Release and supports both a
  direct increment and a wider source catch-up.
- [ ] One successful update creates one deterministic next Release whose
  predecessor is the previous latest Release.
- [ ] Existing Release identity, objects, fields, and provenance remain
  immutable.
- [ ] Readers can list and open both Releases after publication.
- [ ] Bootstrap, incremental, and catch-up policy remain internal; the product
  exposes only Update outcome and Release history.
- [ ] The Data page shows the new latest Release without losing the first.

**How to verify:**

- Run `uv run pytest -q tests/adapters tests/integration tests/acceptance` with
  Fixture data containing direct and wider source gaps.
- Run `bun run --cwd web test:e2e` and confirm two successful updates retain
  ordered Release history and select the second as latest.

## Comments
