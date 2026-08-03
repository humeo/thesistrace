# 06 — Record Publication atomically in PostgreSQL

**What to build:** Complete the shared Publication contract so a product module
can record a manifest in its transaction and expose only committed, verified
immutable truth.

**Blocked by:** 05.

**Status:** ready-for-agent

**Implementation:** complete

- [x] Publication owns its manifest, object, and manifest-object schema, SQL,
  migrations, and checksum metadata.
- [x] `record` writes Publication state through the caller's concrete
  PostgreSQL transaction and never commits or updates a product schema.
- [x] A product reference becomes visible only when the caller commits its own
  lifecycle change and the Publication records once.
- [x] The committed manifest and PublishedRef retain the caller-supplied
  provenance, and verified read returns it only after validating the complete
  manifest and objects.
- [x] An upload followed by PostgreSQL rollback leaves only an invisible orphan
  and preserves the previous product reference.
- [x] Readers start from a committed PostgreSQL reference and verify the full
  manifest and every S3 object.
- [x] Orphans can be identified without turning Publication into a product
  object browser.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written. It resets the dedicated PostgreSQL/RustFS test state, runs the
architecture and integration contracts against those real services, and
always stops them afterward.

```sh
set -eu
cleanup() { ./scripts/core-test-runtime down; }
trap cleanup EXIT

./scripts/core-test-runtime reset
./scripts/core-test-runtime run \
  uv run pytest -q tests/architecture tests/integration
```

The suite must inject rollback after upload and corruption after commit. The
orphan must remain absent from PostgreSQL product truth, the previous product
reference must remain unchanged, and a corrupt committed bundle must be
rejected before any payload bundle is returned.

## Comments

- TDD red begins with the committed-publication contract importing the missing
  `PublicationNotFoundError`; Publication currently has no PostgreSQL schema,
  `record`, committed `read`, or orphan-discovery behavior.
- TDD green: the focused real-service contract passed `3 passed`. It verifies
  idempotent recording inside one caller transaction, invisibility before
  commit, complete visibility after commit, rollback preservation of the prior
  product reference, orphan identification, and corrupt-object rejection.
- Publication migrations own `objects`, `manifests`, and `manifest_objects`.
  `record` accepts the concrete caller transaction, issues no commit, and has
  no SQL for Data, Definitions, ResearchRuns, or DailyTracks.
- `read` first resolves the committed manifest checksum in PostgreSQL, compares
  the manifest/object/link records, validates PublishedRef kind and provenance,
  and only then verifies every S3 byte before returning one complete bundle.
- Orphan discovery returns only unrecorded content digests to internal cleanup;
  it exposes no physical bucket, key, browser, or payload access.
- The exact clean-state command above passed `21 passed` in `2.41s`; cleanup
  stopped both containers and removed only the dedicated test state.
- Review round 1 fix: orphan discovery now requires an explicit timezone-aware
  `uploaded_before` cutoff, ignores newer in-flight uploads, and reads committed
  PostgreSQL truth after the S3 snapshot to narrow the concurrent-record race.
  The result remains a candidate digest set only; later cleanup must use an aged
  cutoff and recheck rather than treating a fresh upload as deletable.
- Committed read now compares PostgreSQL's separately stored manifest schema
  version with the checksummed canonical manifest. A post-commit corruption
  probe changes that column to `999` and verifies the whole read is rejected.
- Post-review focused verification passed `4 passed`; the exact clean-state
  command above passed `22 passed` in `1.31s`.
- Final independent review: Standards PASS and Spec PASS after two rounds. The
  reviewer reran the exact command from clean state: `22 passed` in `1.13s`,
  with PostgreSQL/RustFS cleanup successful.
- Final repository gate shared with Ticket 05: `make check` passed with Ruff
  clean, `467 passed, 34 skipped` in Python (`363.94s`), Web typecheck and
  production build green, and the narrow/desktop browser chains passing in
  `29.3s` and `27.9s`.
