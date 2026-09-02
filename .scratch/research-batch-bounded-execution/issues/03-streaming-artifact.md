# Stream the private Alpha-and-Factor artifact

**Status:** ready-for-agent

Replace the v1 all-bytes artifact with one v2 framed file that is incrementally
written, validated, published, materialized, and consumed.

## Acceptance

- Incomplete `.partial` files never become authoritative.
- Corruption, truncation, binding drift, and early-final frames are rejected.
- Publication staging and recording do not retain every payload body in memory.

## Comments
