---
status: superseded by ADR-0018
---

# Append financial revisions and query them point in time

ThesisTrace retains every company disclosure and later restatement as an
immutable Financial Revision. Each revision records the instrument, reporting
period, source publication value, derived `available_from_session`, and a
deterministic revision identity. Ingestion deduplicates repeated source records
but never overwrites an earlier disclosed version with a later one.

For a historical market session, `equity.financial_pit` selects the latest
revision whose `available_from_session` is not later than that session. A
session before a restatement therefore sees the original disclosure, while a
session after it sees the restated values.

Dataset Release immutability alone is insufficient for this behavior: a newer
release used to research a long historical interval must still contain the
revision timeline needed to reconstruct what was knowable on every date.
Financial revision history is therefore part of the canonical data product,
not merely retained in older releases.
