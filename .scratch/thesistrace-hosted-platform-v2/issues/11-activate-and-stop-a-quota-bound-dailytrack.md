# 11 — Activate and stop a quota-bound DailyTrack

**What to build:** Let a User idempotently activate Daily Tracking from one
successful ResearchRun, inspect its owned root state, and stop it permanently
while enforcing the Personal Workspace Active DailyTrack limit.

**Blocked by:** 07 — Run one Research Workflow through Temporal; 09 — Enforce the Personal Workspace Quota Profile; `thesistrace-bounded-research-storage/04 — Seed a bounded Working Cache when activating DailyTrack`.

**Status:** ready-for-agent

- [ ] Only a succeeded ResearchRun with a complete Result Bundle can seed a Personal Workspace-owned DailyTrack.
- [ ] Activation pins the frozen Definition, Dataset Release, Tracking Origin, numeric contract, and Terminal Strategy State and publishes one Activation Checkpoint plus the bounded latest-only Working Cache.
- [ ] Repeating an activation idempotency key returns the same DailyTrack and does not consume another active-Track quota unit.
- [ ] Activation is rejected with the active-Track quota dimension when the effective Personal Workspace limit is reached, including a lower Operator override.
- [ ] A valid identifier from another Personal Workspace cannot activate, inspect, or stop the Track and receives no existence disclosure.
- [ ] Stopping a Track is terminal, fences queued or running later publication, releases the active-Track quota immediately, and durably schedules idempotent Working Cache cleanup.
- [ ] A seed ResearchRun cannot be deleted while a retained DailyTrack still references it.
