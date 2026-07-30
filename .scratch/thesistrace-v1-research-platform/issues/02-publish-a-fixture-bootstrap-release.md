# 02 — Publish a fixture Bootstrap Release

**What to build:** Allow the operator to bootstrap deterministic fixture data
and atomically publish the predecessor-free root Dataset Release through the
same application boundary used by the product.

**Blocked by:** 01 — Start the empty Web Workspace.

**Status:** ready-for-agent

- [ ] The fixture covers at least 756 Research Sessions and enough instruments for Factor sample rules.
- [ ] Bootstrap writes immutable source and canonical objects before committing the Release manifest.
- [ ] The root Release records no predecessor, the complete bootstrap session range, an empty correction change-set, schemas, object identities, and checksums.
- [ ] Repeating the same idempotent Bootstrap request does not create another logical Release.
- [ ] Any failed validation leaves the prior latest pointer and all published manifests unchanged.
- [ ] The API and Web UI expose Bootstrap progress, success, failure, and root Release provenance.
