# 11 — Publish a later Dataset Release

**What to build:** Publish later canonical sessions as the next immutable
Dataset Release while preserving every earlier Release and its provenance.

**Blocked by:** 10.

**Status:** ready-for-agent

**Implementation:** complete

- [x] Collection starts from the latest successful Release and supports both a
  direct increment and a wider source catch-up.
- [x] One successful update creates one deterministic next Release whose
  predecessor is the previous latest Release.
- [x] Existing Release identity, objects, fields, and provenance remain
  immutable.
- [x] Readers can list and open both Releases after publication.
- [x] Bootstrap, incremental, and catch-up policy remain internal; the product
  exposes only Update outcome and Release history.
- [x] The Data page shows the new latest Release without losing the first.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/adapters \
  tests/integration \
  tests/acceptance/test_core_fixture_data_update.py \
  tests/acceptance/test_core_later_data_update.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:core
./scripts/core-test-runtime down
```

The suite must cover a direct next session and a wider source catch-up through
the same Data action. The browser must publish two Releases from `/data`, retain
both in history, and select the second as latest without exposing collection
policy or provider mode.

## Comments

- Data resolves the latest successful Release and passes only its last Research
  Session to `CollectionPlan.incremental`; the Fixture adapter still knows no
  Release identity or storage concept.
- A direct source frontier adds one Research Session. A wider configured source
  frontier adds three sessions in one collection, but both use the same Data
  worker, validation, Publication, fencing, and PostgreSQL commit path.
- Each manifest-derived Release ID is deterministic, records the prior latest
  Release as predecessor, and is committed only if that prior latest remains
  current. Earlier Release rows, Publication objects, field links, provenance,
  and readable canonical payloads remain unchanged.
- Real PostgreSQL/RustFS acceptance passed both direct and wider cases (`2
  passed, 1 warning` in `9.18s`). The Data page now refreshes Release history;
  real `/data` Playwright acceptance published two Releases, retained both,
  selected the 757-session Release as latest, and passed in `15.1s`.
- Focused Ruff, `13` architecture tests, TypeScript, and Web build passed.
