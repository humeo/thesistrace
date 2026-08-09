# 14 — Execute each Attempt against its start-time Head

**What to build:** Execute a queued ResearchRun through the Worker against the
Dataset Head selected and pinned when its Attempt starts, then atomically
publish the dated Result and accurate provenance.

**Blocked by:** 01 — Run explicit Research Periods in the Kernel; 04 — Publish variable-length four-value Result Bundles; 07 — Select and protect one Dataset Head atomically; 13 — Admit dated ResearchRuns against current Data.

**Status:** ready-for-agent

- [ ] If a Run is admitted while Head A is current and Head moves to B before Attempt start, that Attempt selects and pins B.
- [ ] After an Attempt has selected A and entered running, a move to B cannot alter its input; its Result matches an independent reference using A only.
- [ ] Attempt start re-maps the inclusive dates and revalidates Coverage, frozen fields, Dataset Schema, and required in-period facts against its selected Generation.
- [ ] Missing complete Calculation Warm-up produces a stable terminal insufficient-warm-up domain failure, preserves Requested Research Dates, publishes no partial Result, and does not trigger automatic infrastructure retry.
- [ ] Valid one-session, two-session, and longer Runs publish the exact period's Strategy Daily Observations, nullable short-sample metrics, and complete Terminal Strategy State.
- [ ] A successful Run records its actual `data_generation_id` and data-through session in Run and Attempt provenance outside the four-value Result; no Generation becomes a user-selectable or browseable resource.
- [ ] Result object write, manifest record, or final-state failure cannot expose partial content or mark the Run succeeded; terminal execution releases its active Generation pin.
- [ ] Real HTTP, Worker, PostgreSQL, RustFS, and temporary-mount acceptance reopens a successful Run after restart without re-execution.
