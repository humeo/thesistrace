# 22 — Qualify the single-node capacity envelope

**What to build:** Prove the complete Hosted stack can execute the representative
maximum research and publication load inside the accepted single-node resource
envelope before any invited User is admitted.

**Blocked by:** 10 — Publish Datasets on the independent Data Worker; 14 — Lock down the five-Worker topology; 15 — Dispatch P1 and P3 work fairly; 16 — Enforce private storage and disk admission; 19 — Operate three bounded Health views.

**Status:** ready-for-agent

- [x] Capacity acceptance runs four simultaneous Top3000 maximum Compute Activities while one Dataset Publication and every steady service are present.
- [x] Each Compute Worker records p99 memory at or below `700 MiB`, absolute peak at or below `800 MiB`, and correct completion within its `1 GiB` and `0.75` CPU container limits.
- [x] The complete run has no swap, OOM kill, unexpected container restart, missing heartbeat, duplicate publication, or incorrect result under CPU throttling.
- [x] Non-Worker service limits total no more than `5 GiB` and `2` CPU cores.
- [ ] Capacity evidence records the qualifying Docker runtime or host's total logical CPU and memory and proves all Worker and non-Worker limits leave at least `2 GiB` memory and `0.5` CPU outside container budgets; under the current envelope this requires at least 6 logical CPU and 12 GiB.
- [x] Dataset Publication remains isolated on its Data slot and does not reduce the four-slot Compute limit during the measurement.
- [x] Capacity evidence is produced from the production Parquet, Result Bundle, Working Cache, PostgreSQL, Temporal, and ObjectStore paths rather than synthetic encodings or fixture-only shortcuts.
- [ ] Invitation issuance rejects legacy or incomplete evidence without same-runtime host totals and remains disabled until a matching current Release passes the complete Capacity Qualification.

## Comments

- Added a bounded columnar research engine that reads production partitioned
  Parquet without materializing the complete three-year release, produces the
  existing Factor and Strategy result contracts, and was checked for exact
  equivalence against the prior engine. Live Dataset Publication now writes
  bounded static and session partitions through the production ObjectStore.
- Added an immutable PostgreSQL capacity-qualification ledger, operator CLI,
  invitation launch gate, Top3000 qualification corpus, Temporal qualification
  workflows, cgroup sampling, retry-safe Workflow result recovery, and fixed
  Worker attempt evidence. Heavy Activities use a two-minute heartbeat timeout
  while the heartbeat loop continues to retry transient delivery timeouts.
- The final isolated run used Release Bundle
  `0.1.0-adfe4da13576e552`, 756 sessions and 3,000 instruments. Four concurrent
  Compute Activities completed exactly once on four distinct slots with
  identical Alpha checksum
  `36c4f211671bf61939dcbe580ec4ba9202712fd7b1a6c5c07c35a4cb2701f2db`
  and Strategy checksum
  `009ee2df0137093a7526140ebe08669fb5b523d7a2fe8b83056164a363e8f78d`.
  Their p99 memory was 275.28–293.23 MiB and their absolute peaks were
  277.98–295.87 MiB.
- The simultaneous Dataset Publication completed exactly once on `data-1`.
  The run recorded no swap, OOM kill, restart, missing heartbeat, duplicate
  publication, or incorrect result. Non-Worker limits totalled 4,992 MiB and
  1.95 CPU, and all production-path assertions passed. The authoritative raw
  evidence is in `evidence/22-capacity-qualification.json`.
- Real gate acceptance in the isolated PostgreSQL deployment proved invitation
  issuance is rejected with `CAPACITY_QUALIFICATION_REQUIRED` both before any
  qualification and after a failed qualification, then succeeds only after the
  passing evidence is recorded. This exposed and fixed the operator command
  running under the intentionally restricted API database role; it now uses
  the existing one-shot administrative database boundary.
- Reopened on 2026-08-02 after verifying the current development Docker runtime
  exposes 2 logical CPU and about 3.83 GiB. The existing evidence proves the
  four Top3000 Activities, Data Publication, checksums, Worker memory, and
  container failure observations recorded above, but it contains no runtime
  total CPU or memory. It therefore remains workload evidence, not sufficient
  proof of the required host reserve or a valid Launch Qualification input.
