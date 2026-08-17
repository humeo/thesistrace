# 02 — Run fixed-role single-slot Worker pools

**What to build:** Run Research and DailyTrack work in independently scalable Worker
pools while preserving one Production Image and one executable. Each Worker owns one
explicit execution slot, claims only its configured role, and keeps the existing short
Research and Tracking journeys operational through the new topology.

**Blocked by:** 01 — Hard-cut Product State while preserving Canonical Data

**Status:** ready-for-agent

- [ ] The Worker executable requires one immutable startup role, `research` or `tracking`, and never falls back to the other role.
- [ ] A Research Worker claims only ResearchRun work and a Tracking Worker claims only Tracking Advance work.
- [ ] Every Worker has exactly one execution slot and owns at most one active Attempt; one process never runs several product executions concurrently.
- [ ] Development starts one Research Worker and one Tracking Worker from the same Production Image and executable.
- [ ] Development and test declare 2 vCPU and 2 GiB for each Worker, with at most two calculation threads and 1.5 GiB available to execution planning.
- [ ] Worker startup fails clearly when actual cgroup CPU or memory limits are below the selected role's declaration.
- [ ] Research and Tracking capacity declarations and replica counts can be changed independently without changing calculation semantics.
- [ ] Adding replicas permits different Runs or Tracks to execute concurrently while PostgreSQL claims and fences prevent duplicate ownership.
- [ ] Product work is checked before shared maintenance; an idle Worker may reclaim at most one pending Publication object per poll.
- [ ] Only Tracking Workers reconcile disposable Tracking Working Caches.
- [ ] The old mixed Worker polling loop and any implicit priority from Research polling followed by Tracking draining are removed.
- [ ] There is no third Worker role, generic dispatch layer, event bus, Redis queue, Temporal workflow, or duplicate execution engine.
- [ ] Existing short ResearchRun and DailyTrack success paths pass through real role-specific Worker processes in isolated integration and Production Image smoke tests.
- [ ] Structured startup and claim logs identify Worker role, declared capacity, slot ownership, and claimed business resource without logging secrets.

## Comments

- Parent: Scalable Long Research and Daily Tracking Execution.
- Serial predecessor: Ticket 01.
