---
status: accepted
---

# Roll back release bundles with expand-contract schema changes

Every Hosted Platform V2 deployment retains the immediately preceding,
immutable release bundle. The bundle pins the compatible Caddy Web image,
ThesisTrace API and Worker images, InsForge release, Temporal release, migration
jobs, and configuration schema rather than rolling individual components back
to an untested mixture.

Application database changes follow expand/contract. A release first adds the
new schema while retaining the old representation required by the preceding
release. Destructive column, table, constraint, or representation removal
occurs only in a later cleanup release after the compatibility period. A failed
new release may therefore switch back to the preceding images without running
a reverse schema migration.

Hosted Platform V2 does not provide automatic down migrations. If a data change
cannot remain backward-compatible, its release is explicitly classified as
requiring full restore for rollback. The operator verifies a coordinated
pre-release PostgreSQL and InsForge Storage backup before applying that change;
rollback restores that complete recovery point rather than attempting to
partially reverse mutated rows or objects.

Old-schema cleanup is a separately observable release step and never occurs in
the same release that first makes the new schema authoritative.
