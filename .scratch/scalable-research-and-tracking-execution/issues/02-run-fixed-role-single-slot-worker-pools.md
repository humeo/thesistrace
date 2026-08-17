# 02 — Run fixed-role single-slot Worker pools

**What to build:** Run Research and DailyTrack work in independently scalable Worker
pools while preserving one Production Image and one executable. Each Worker owns one
explicit execution slot, claims only its configured role, and keeps the existing short
Research and Tracking journeys operational through the new topology.

**Blocked by:** 01 — Hard-cut Product State while preserving Canonical Data

**Status:** complete

- [x] The Worker executable requires one immutable startup role, `research` or `tracking`, and never falls back to the other role.
- [x] A Research Worker claims only ResearchRun work and a Tracking Worker claims only Tracking Advance work.
- [x] Every Worker has exactly one execution slot and owns at most one active Attempt; one process never runs several product executions concurrently.
- [x] Development starts one Research Worker and one Tracking Worker from the same Production Image and executable.
- [x] Development and test declare 2 vCPU and 2 GiB for each Worker, with at most two calculation threads and 1.5 GiB available to execution planning.
- [x] Worker startup fails clearly when actual cgroup CPU or memory limits are below the selected role's declaration.
- [x] Research and Tracking capacity declarations and replica counts can be changed independently without changing calculation semantics.
- [x] Adding replicas permits different Runs or Tracks to execute concurrently while PostgreSQL claims and fences prevent duplicate ownership.
- [x] Product work is checked before shared maintenance; an idle Worker may reclaim at most one pending Publication object per poll.
- [x] Only Tracking Workers reconcile disposable Tracking Working Caches.
- [x] The old mixed Worker polling loop and any implicit priority from Research polling followed by Tracking draining are removed.
- [x] There is no third Worker role, generic dispatch layer, event bus, Redis queue, Temporal workflow, or duplicate execution engine.
- [x] Existing short ResearchRun and DailyTrack success paths pass through real role-specific Worker processes in isolated integration and Production Image smoke tests.
- [x] Structured startup and claim logs identify Worker role, declared capacity, slot ownership, and claimed business resource without logging secrets.

## Comments

- Parent: Scalable Long Research and Daily Tracking Execution.
- Serial predecessor: Ticket 01.
- Plan: hard-cut the mixed polling loop into immutable Research and Tracking roles,
  enforce one declared slot and cgroup capacity at startup, then prove role isolation,
  maintenance ordering, replica ownership, and final-image behavior at real boundaries.
- Implemented: one executable now serves two fixed-role Compose pools from the same
  backend image; each replica owns one synchronous slot, independent 2C2G defaults,
  a 1.5-GiB planning envelope, two calculation threads, and structured startup/claim
  evidence. Product work precedes bounded maintenance and only Tracking reconciles cache.
- Verification: `pnpm test` passed 484 Python and 25 Web tests; isolated integration
  passed 156 tests plus database restart. E2E passed 3/3. Production Image smoke run
  `20260817t173718z-49646-be139767` passed both roles, restart, short Research/Tracking,
  structured logs, and real CPU/memory cgroup rejection.
- Review: Spec and Standards independently reviewed the staged diff. Capacity was kept
  at the current Worker boundary instead of adding an unused future planner seam;
  duplicate ownership was strengthened to a durable-claim subprocess barrier; both
  final re-reviews passed with no material findings.
- Delivery: implementation and this terminal tracker update are finalized together
  in the Ticket 02 commit.
