# 06 — Record Publication atomically in PostgreSQL

**What to build:** Complete the shared Publication contract so a product module
can record a manifest in its transaction and expose only committed, verified
immutable truth.

**Blocked by:** 05.

**Status:** ready-for-agent

- [ ] Publication owns its manifest, object, and manifest-object schema, SQL,
  migrations, and checksum metadata.
- [ ] `record` writes Publication state through the caller's concrete
  PostgreSQL transaction and never commits or updates a product schema.
- [ ] A product reference becomes visible only when the caller commits its own
  lifecycle change and the Publication records once.
- [ ] The committed manifest and PublishedRef retain the caller-supplied
  provenance, and verified read returns it only after validating the complete
  manifest and objects.
- [ ] An upload followed by PostgreSQL rollback leaves only an invisible orphan
  and preserves the previous product reference.
- [ ] Readers start from a committed PostgreSQL reference and verify the full
  manifest and every S3 object.
- [ ] Orphans can be identified without turning Publication into a product
  object browser.

**How to verify:**

- Run `uv run pytest -q tests/architecture tests/integration` with real
  PostgreSQL and RustFS.
- Inject rollback after upload and corruption after commit; confirm the orphan
  stays invisible and the committed corrupt bundle is rejected on read.

## Comments
