# 38 — Certify Hosted Local Acceptance on a Clean 2C4G Runtime

**Parent:** 24 — Deliver Hosted Local Acceptance on 2C4G.

**What to build:** Run the completed gate set once from a clean local state on
the configured 2C4G Docker runtime and emit the sole final Hosted Local
Acceptance result. This certifies the development acceptance contract only; it
does not qualify or launch production.

**Blocked by:** 30 — Prove Local PostgreSQL, Edge, and Storage Boundaries; 31 — Prove API and Outbox Relay Durable Recovery; 32 — Prove Compute Activity Heartbeat Recovery; 33 — Prove Dataset Publication Redelivery and Storage Reconciliation; 34 — Prove Controlled Workflow Scheduling and Exhaustion Semantics; 35 — Prove the Bounded Local Operational Health Profile; 36 — Prove Local Cold Restart and Compact Restore; 37 — Prove the Staged Web through Local Browser Flows.

**Status:** ready-for-agent

- [ ] The final run starts with no prior acceptance containers, networks, volumes, checkpoints, or evidence, creates a new state epoch, and uses empty authoritative volumes rather than a resumed or manually repaired session.
- [ ] The configured Docker runtime exposes 2 logical CPU and approximately 4 GiB, and the evidence records exact host/runtime, source/worktree, Release Bundle, image, migration, Compose, configuration, dependency-lock, and Web build fingerprints.
- [ ] The canonical sequence runs every required Core, product, PostgreSQL/edge/storage, API/relay recovery, Compute recovery, Dataset Publication recovery, controlled workflow, operational Health, cold-restart/restore, and browser gate exactly once with no skipped requirement or reused checkpoint.
- [ ] Heavy phases remain serial, observability runs only during its bounded phase, one Compute Worker and the separate Data Worker are used, and Compute Workers 2–4 consume no resources.
- [ ] The complete run finishes without swap, OOM kill, unexpected container restart, missing required heartbeat, silent timeout extension, or an unhealthy required service; total duration and per-gate CPU, memory, disk, restart, and heartbeat peaks are recorded as diagnostic observations.
- [ ] Final evidence uses only the `hosted-v2-local-v1` schema, sets `launch_qualified` to false, is never signed with the Launch Qualification key, never invokes `acceptance-record-launch`, never opens Registration Invitation admission, and is rejected by every production launch-evidence consumer.
- [ ] The final summary explicitly lists physical production capacity, co-resident maximum load, off-node recovery, Cloudflare and external DNS/TLS, real SMTP delivery, production invitation admission, and Launch Qualification as not claimed.
- [ ] On failure, the first failing gate and its preserved diagnostic state, logs, evidence, cleanup command, and invalidated downstream gates are reported. On success, guarded cleanup removes only the final run's disposable resources while retaining its evidence.
- [ ] A concise runbook documents the clean-run command, expected long heartbeat waits, phase order, evidence location, safe diagnostic retry commands, guarded cleanup, and the distinction between development acceptance and production qualification.
