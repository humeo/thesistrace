---
status: accepted
---

# Hard-cut result-changing calculation contracts

The active ThesisTrace product executes exactly one calculation kernel and
Numeric Execution Contract. ResearchRuns and DailyTracks record its exact
identity for validation and provenance, but the runtime contains no historical
contract dispatcher, Tracking Generation branch, compatibility reader, or
automatic full-recalculation path.

A result-changing kernel or contract update is a Product State hard cut. The
new runtime refuses to execute against Product State accepted under a different
contract identity. During Development, the operator uses ADR-0207's
identity-checked `pnpm dev:reset`, which removes Research and DailyTrack Product
State while preserving the mounted Canonical Data Store and Dataset Head.

ThesisTrace does not migrate, resume, reinterpret, or silently continue an old
DailyTrack under new semantics. A future stable-deployment upgrade policy would
require a new explicit decision; no dormant branching model is retained in the
current product for that possibility.

This supersedes only ADR-0109's requirement to create a new Tracking Generation
and fully execute another result branch after a semantic correction. ADR-0109's
exact arithmetic, serialization, recorded contract identity, and rule that Data
Refresh never rewrites published Track history remain accepted.
