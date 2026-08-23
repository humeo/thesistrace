---
status: accepted
---

# Use a mounted current Dataset Head and temporary Data Generations

ThesisTrace operates one mounted Canonical Data Store whose Dataset Head points
to the current complete validated Data Generation. Startup validates that Head
without contacting Tushare; only explicit Data Operator bootstrap or refresh
builds a complete candidate beside it and atomically moves the pointer.

A Data Generation is a temporary consistency and pinning boundary, not a
permanent product resource or user-selectable release. ResearchRun admission
freezes one Generation under ADR-0190, each Tracking Advance Attempt pins the
current Generation for that Attempt, and unreferenced predecessor objects may
be collected after all durable retentions and execution pins are released.

Published Research and Tracking state remains immutable when the Dataset Head
advances. The system intentionally does not retain a navigable release chain or
promise that an unpinned historical Generation can be reconstructed; this
trades permanent data-version retention for one current operational dataset
while preserving every active calculation's input consistency.
