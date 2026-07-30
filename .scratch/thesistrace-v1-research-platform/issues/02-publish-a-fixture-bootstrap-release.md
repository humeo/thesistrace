# 02 — Publish a fixture Bootstrap Release

**What to build:** Allow the operator to bootstrap deterministic fixture data
and atomically publish the predecessor-free root Dataset Release through the
same application boundary used by the product.

**Blocked by:** 01 — Start the empty Web Workspace.

**Status:** resolved

- [x] The fixture covers at least 756 Research Sessions and enough instruments for Factor sample rules.
- [x] Bootstrap writes immutable source and canonical objects before committing the Release manifest.
- [x] The root Release records no predecessor, the complete bootstrap session range, an empty correction change-set, schemas, object identities, and checksums.
- [x] Repeating the same idempotent Bootstrap request does not create another logical Release.
- [x] Any failed validation leaves the prior latest pointer and all published manifests unchanged.
- [x] The API and Web UI expose Bootstrap progress, success, failure, and root Release provenance.

## Comments

- Added a deterministic 756-session, 35-instrument fixture, content-addressed
  immutable source/canonical objects, and atomic root Manifest publication.
- Verified idempotency, failure atomicity, object ETags, Web progress, and root
  provenance through public API and browser acceptance.
