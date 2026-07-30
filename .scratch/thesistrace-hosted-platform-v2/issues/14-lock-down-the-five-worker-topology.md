# 14 — Lock down the five-Worker topology

**What to build:** Run four isolated single-slot Compute Workers and one
separate single-slot Data Worker with the least privileges, storage access, and
network egress needed for their accepted Activities.

**Blocked by:** 08 — Recover, cancel, and fence Research Workflows; 10 — Publish Datasets on the independent Data Worker; 12 — Advance DailyTrack through finite Workflows; `thesistrace-bounded-research-storage/04 — Seed a bounded Working Cache when activating DailyTrack`.

**Status:** ready-for-agent

- [ ] Exactly four long-lived Compute Worker containers each execute at most one heavy Compute Activity, and one separately budgeted Data Worker executes at most one Dataset Publication Activity.
- [ ] Compute Workers run non-root with read-only root filesystems, bounded private scratch, no Docker socket, no privileged capabilities, and no physical immutable-Storage volume mount.
- [ ] Compute Workers have no general Internet or Tushare egress; the Data Worker alone has the separate Tushare egress path required by Dataset Publication.
- [ ] All four identical Compute Workers can execute either P1 or P3 work and mount the same controlled shared WorkingCacheStore needed for Tracking; tier preference comes from Temporal dispatch rather than fixed Worker roles, while immutable objects remain reachable only through the private ObjectStore port.
- [ ] API, outbox relay, Data Worker, Compute Workers, Storage, PostgreSQL, Temporal, and telemetry use separate least-privilege identities, database roles, network paths, and secrets.
- [ ] Each Compute Worker is capped at `1 GiB` memory and `0.75` CPU, the Data Worker at `1 GiB` and `0.5` CPU, and one Worker crash does not terminate another slot.
- [ ] Container-level acceptance proves the denied mounts, capabilities, egress paths, and cross-role credentials rather than relying only on application configuration.
