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
DailyTrack under new semantics, and retains no dormant branching model.
