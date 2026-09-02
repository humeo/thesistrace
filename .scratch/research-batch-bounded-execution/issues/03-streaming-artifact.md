# Stream the private Alpha-and-Factor artifact

**Status:** complete

Replace the v1 all-bytes artifact with one v2 framed file that is incrementally
written, validated, published, materialized, and consumed.

## Acceptance

- Incomplete `.partial` files never become authoritative.
- Corruption, truncation, binding drift, and early-final frames are rejected.
- Publication staging and recording do not retain every payload body in memory.

## Comments

- 2026-09-03: Implemented the hard-cut v2 framed artifact, incremental partial
  writer, streaming publication verification, Strategy partition ledger, and
  corruption/binding/truncation rejection in `141594d`. The full release gate
  passed at `d2adced`.
