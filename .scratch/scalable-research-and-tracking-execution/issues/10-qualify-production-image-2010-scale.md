# 10 — Qualify the complete Production Image at 2010 scale

**What to build:** Prove that the final hard-cut execution product supports a complete
2010-scale Research workload within its 2c2g envelope and that the built images retain
correct Research recovery, DailyTrack recovery, cancellation, Stop, restart, and
offline Canonical Data behavior. The gate records reproducible evidence and rejects
obsolete or partial execution paths.

**Blocked by:** 09 — Confirm DailyTrack Stop and reclaim Working Cache

**Status:** complete

- [x] The Reference Long Research Workload evaluates `rank(pct_change(close_adj, 20))` over the Top 3000 Liquidity Universe from 2010-01-04 through 2026-08-13 against one frozen representative Data Generation.
- [x] The benchmark uses the complete path: admission and frozen plan, selective reads, Alpha, 1-, 5-, and 20-session Factor Evaluation, Strategy Backtest, Chunk Checkpoints, finalization, and atomic Result publication.
- [x] The final Production Image runs one single-slot Research Worker with 2 vCPU, 2 GiB hard memory, 1.5 GiB execution budget, and at most two calculation threads.
- [x] Five measured cold samples and five measured warm samples use fresh ResearchRuns and exclude queue waiting time.
- [x] Cold samples begin without prior scans of referenced immutable objects; warm samples preload only those same data objects and do not reuse Product State.
- [x] Cold execution P95 is no more than ten minutes and warm execution P95 is no more than five minutes.
- [x] Peak process RSS is no more than 1.5 GiB, the first durable Checkpoint commits within 45 seconds of `running`, and healthy-supervisor cancellation reaches terminal `cancelled` within five seconds.
- [x] Evidence records image revision, capacity declaration, Chunk plan, sample durations, P95 values, peak RSS, first-Checkpoint latency, cancellation latency, objects opened, bytes read, process exits, and final manifest identity.
- [x] Production Image smoke starts separate Research and Tracking Workers from the same image and verifies role restriction, one-slot ownership, cgroup validation, API and web readiness, and structured lifecycle logs.
- [x] Smoke executes a long Research, resumes after Worker loss, confirms cancellation, advances Tracking, exercises transient Retry and explicit Retry, confirms Stop, and survives application and database restart.
- [x] Smoke verifies mounted Canonical Data is usable offline and ordinary Product State Reset does not require Tushare or erase the Dataset Head.
- [x] Market-only work reads no Financial Data, mixed work reads only required fields and partitions, and descriptor, claim, Pin, and progress operations avoid unnecessary Parquet scans.
- [x] Architecture and image checks prove the total-work rejection for valid long Research, mixed Worker loop, whole-period Python-row execution, immediate Stop, resource-exhaustion retry, alternate engine, migration, compatibility, and fallback paths are absent.
- [x] Failures preserve logs, exit codes, API responses, Run and Track state, Attempt and Cycle history, Checkpoint and Publication manifests, timing samples, cgroup facts, and image version.
- [x] The complete fast, integration, browser E2E, Production Image smoke, and benchmark release gates pass from the documented local commands in isolated environments.
- [x] The fixed reference dates remain a reproducible regression fixture rather than a user-facing SLA or maximum supported date.

## Comments

- Parent: Scalable Long Research and Daily Tracking Execution.
- Serial predecessor: Ticket 09.
- Completing this ticket is the final feature gate before the parent Spec can move to `complete`.
- Final Production Image benchmark: `20260818t111846z-22478-c0c9d55e`.
  It exercised the fixed 2010-01-04 through 2026-08-13 workload in 70 fixed
  Chunks. Cold P95 was 240324.084 ms, warm P95 was 261963.959 ms, peak RSS was
  837390336 bytes, first durable Checkpoint latency was 3885.582 ms, and
  cancellation latency was 701.742 ms.
- Final fast gate: 513 Python tests and 29 Web tests passed.
- Final real-dependency integration gate: `20260818t120823z-32695-c69baec7`,
  with 180 integration tests and the database-restart recovery test passing.
- Final browser E2E gate: `20260818t121325z-35931-c79de0cf`, 4 tests passed.
- Final Production Image smoke: `20260818t121556z-36689-77365206`, including
  Worker loss/resume, cancellation, transient and explicit Tracking Retry,
  Stop, application/database restart, and offline Product State Reset.
