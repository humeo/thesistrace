# 14 — Lock down the five-Worker topology

**What to build:** Run four isolated single-slot Compute Workers and one
separate single-slot Data Worker with the least privileges, storage access, and
network egress needed for their accepted Activities.

**Blocked by:** 08 — Recover, cancel, and fence Research Workflows; 10 — Publish Datasets on the independent Data Worker; 12 — Advance DailyTrack through finite Workflows; `thesistrace-bounded-research-storage/04 — Seed a bounded Working Cache when activating DailyTrack`.

**Status:** resolved

- [x] Exactly four long-lived Compute Worker containers each execute at most one heavy Compute Activity, and one separately budgeted Data Worker executes at most one Dataset Publication Activity.
- [x] Compute Workers run non-root with read-only root filesystems, bounded private scratch, no Docker socket, no privileged capabilities, and no physical immutable-Storage volume mount.
- [x] Compute Workers have no general Internet or Tushare egress; the Data Worker alone has the separate Tushare egress path required by Dataset Publication.
- [x] All four identical Compute Workers can execute either P1 or P3 work and mount the same controlled shared WorkingCacheStore needed for Tracking; tier preference comes from Temporal dispatch rather than fixed Worker roles, while immutable objects remain reachable only through the private ObjectStore port.
- [x] API, outbox relay, Data Worker, Compute Workers, Storage, PostgreSQL, Temporal, and telemetry use separate least-privilege identities, database roles, network paths, and secrets.
- [x] Each Compute Worker is capped at `1 GiB` memory and `0.75` CPU, the Data Worker at `1 GiB` and `0.5` CPU, and one Worker crash does not terminate another slot.
- [x] Container-level acceptance proves the denied mounts, capabilities, egress paths, and cross-role credentials rather than relying only on application configuration.

## Comments

- Four identical one-slot Compute containers share only the bounded
  WorkingCache volume. Compute, Data, API, relay, and Storage run as distinct
  non-root identities with separate PostgreSQL logins and ObjectStore
  capabilities; only the private Storage service mounts immutable objects.
- The private ObjectStore validates canonical JSON and Parquet objects,
  authenticates real backing-store probes, and scopes stage, recovery, guard,
  and Manifest namespaces by service role. Leased nonblocking file locks
  preserve active writers and become recoverable after process failure.
- Data has no direct Internet route. Its only external path is a dedicated
  non-root CONNECT gateway that accepts `api.tushare.pro:443` and rejects every
  other authority; Compute has neither that network nor a Tushare credential.
- The Hosted launcher generates missing role-separated database passwords and
  ObjectStore tokens for both new and existing environment files.
- Verification: full backend suite (`189 passed, 13 skipped`), latest focused
  boundary/Tracking suite (`37 passed, 1 skipped`), real PostgreSQL acceptance
  (`8 passed`), real container boundary and Tushare-egress probe (`1 passed`),
  Ruff, Web typecheck/build, package build, and two independent final reviews
  completed successfully.
