# 22 — Qualify the single-node capacity envelope

**What to build:** Prove the complete Hosted stack can execute the representative
maximum research and publication load inside the accepted single-node resource
envelope before any invited User is admitted.

**Blocked by:** 10 — Publish Datasets on the independent Data Worker; 14 — Lock down the five-Worker topology; 15 — Dispatch P1 and P3 work fairly; 16 — Enforce private storage and disk admission; 19 — Operate three bounded Health views.

**Status:** ready-for-agent

- [ ] Capacity acceptance runs four simultaneous Top3000 maximum Compute Activities while one Dataset Publication and every steady service are present.
- [ ] Each Compute Worker records p99 memory at or below `700 MiB`, absolute peak at or below `800 MiB`, and correct completion within its `1 GiB` and `0.75` CPU container limits.
- [ ] The complete run has no swap, OOM kill, unexpected container restart, missing heartbeat, duplicate publication, or incorrect result under CPU throttling.
- [ ] Non-Worker services remain within `5 GiB` and `2` CPU cores, leaving at least `2 GiB` memory and `0.5` CPU outside container budgets for the host.
- [ ] Dataset Publication remains isolated on its Data slot and does not reduce the four-slot Compute limit during the measurement.
- [ ] Capacity evidence is produced from the production Parquet, Result Bundle, Working Cache, PostgreSQL, Temporal, and ObjectStore paths rather than synthetic encodings or fixture-only shortcuts.
- [ ] Invitation issuance remains disabled when the measured capacity gate is missing or failing.
