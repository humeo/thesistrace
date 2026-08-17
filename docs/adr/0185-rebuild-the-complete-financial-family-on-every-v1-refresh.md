---
status: accepted
---

# Rebuild the complete financial family on every V1 refresh

Every V1 Financial Refresh manually re-requests the complete historical
ordinary-interface `endpoint × instrument` shard set for `income`,
`balancesheet`, and `cashflow`. It does not operate a recent-announcement hot
window, rotating historical reconciliation, or automatic schedule. Each shard
uses its resumable checkpoint, exact duplicate Raw Financial Batches and
Canonical objects are content-addressed and reused, and previously accepted
Source Financial Versions remain referenced even if a later source response no
longer includes them. Newly returned versions and observed corrections append;
source absence never acts as deletion. No candidate financial family is
published until every expected shard passes permission, schema, truncation,
Coverage, and cross-family validation. This accepts a multi-hour refresh and
roughly 16,623 logical source shards at the current 5,541 instrument scope,
plus the fixed balance-sheet pages specified by
[ADR-0192](0192-paginate-the-ordinary-balance-sheet-inside-one-logical-shard.md),
in exchange for detecting every source-visible historical change with one
completeness rule. Market Refresh remains independently publishable under the
one Dataset Head.
