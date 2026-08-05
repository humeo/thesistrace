---
status: superseded by ADR-0151
scope: archived - outside the active Core
---

# Separate Hosted Local Acceptance from Launch Qualification

Hosted Local Acceptance is a non-attested development gate for a constrained
Docker runtime: it uses the real core services with one Compute Worker, runs
Data and Compute load serially, and validates observability separately from
heavy work. Launch Qualification remains the release-bound production gate for
the complete topology, same-node capacity, coordinated recovery, and invitation
admission. A local result must use a distinct evidence schema and runner; it
must never become launch evidence through a skip flag or omitted check.

This separation accepts that a 2-CPU, 4-GiB development runtime can prove real
identity, isolation, lifecycle, RLS, Temporal, Storage, and recovery semantics
without proving four-Worker Top3000 capacity or host recovery objectives. It
prevents constrained-host failures from masquerading as product defects and
prevents a lucky local pass from masquerading as production readiness.
