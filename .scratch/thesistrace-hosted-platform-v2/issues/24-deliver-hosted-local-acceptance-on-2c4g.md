# 24 — Deliver Hosted Local Acceptance on 2C4G

**What to build:** Deliver one repeatable, non-attested acceptance command that
proves the real Hosted V2 product and service boundaries on the current local
Docker runtime with 2 logical CPU and about 3.83 GiB, without claiming or
changing production launch state.

**Blocked by:** 04 — Authenticate Users only through InsForge; 06 — Isolate private research and share read-only Datasets; 07 — Run one Research Workflow through Temporal; 10 — Publish Datasets on the independent Data Worker; 11 — Activate and stop a quota-bound DailyTrack; 12 — Advance DailyTrack through finite Workflows; 17 — Delete terminal resources through Tombstones; 19 — Operate three bounded Health views; 38 — Certify Hosted Local Acceptance on a clean 2C4G runtime; `thesistrace-v1-research-platform/28 — Prove the revised V1 product chain`.

**Status:** ready-for-agent

- [ ] One explicit local command prepares isolated state, runs each phase with a bounded timeout, and writes a phase-by-phase result that identifies the first failed boundary rather than collapsing every failure into one release result.
- [ ] The local core profile uses the pinned production images, migrations, roles, networks, and service implementations but starts only one Compute Worker; the Data Worker remains separate and heavy Compute and Data work run serially. Compute Workers 2–4 and the observability stack consume no resources during the core product phase.
- [ ] Through the real local Public Origin, two Users complete acceptance-mode invitation, InsForge verification, login, idempotent Personal Workspace provisioning, bounded shared Dataset reads, private research creation and execution, result inspection, quota rejection, cancellation or rerun, DailyTrack activation and advancement, stop, Tombstone deletion, and denial of raw or signed Storage access.
- [ ] A disposable real PostgreSQL database with current production migrations enumerates every `workspace_id` table and proves non-disclosing cross-Workspace reads and writes, missing or forged transaction context, and least-privilege behavior through every production service role.
- [ ] A real Temporal Service executes the production ResearchRun and Dataset Publication paths. API, outbox relay, Compute Worker, and Data Worker are interrupted one at a time and recover without duplicate domain results, partial authoritative artifacts, or a lost cancellation fence.
- [ ] Controlled tests cover the four-slot dispatch, P1/P3 progress, retry, and resource-exhaustion contracts without pretending that one local Worker or synthetic exhaustion proves physical production capacity.
- [ ] A separate operational phase starts Collector, Prometheus, and Grafana while heavy work is idle, verifies System Health, Data Health, Quantitative Semantic Health, bounded time series, and telemetry redaction, then releases those resources before any further heavy phase.
- [ ] A bounded local cold-restart and compact backup/restore smoke proves authoritative state and object-index survival without claiming off-node independence, the six-hour recovery-point objective, the eight-hour recovery-time objective, or production whole-node resilience.
- [ ] The complete local run finishes on the configured 2C4G Docker runtime without swap, OOM kill, unexpected container restart, or a missing required heartbeat, and records observed runtime totals and per-phase peaks as diagnostic evidence rather than Capacity Qualification.
- [ ] Local evidence uses a distinct `hosted-v2-local-v1` schema, records that `launch_qualified` is false, is never signed with the Launch Qualification key, never invokes `acceptance-record-launch`, never opens Registration Invitation admission, and is rejected by every production launch-evidence consumer.
- [ ] Relevant backend, frontend typecheck/build, browser, RLS, Temporal, security, storage, and local recovery checks run sequentially; the final summary lists the production-only capacity, off-node recovery, Cloudflare, real SMTP-delivery, and Launch Qualification gates as explicitly not claimed rather than silently passing or skipping them.

## Comments

- Created on 2026-08-02 after live inspection confirmed the development Docker
  runtime exposes 2 logical CPU and 4,109,938,688 bytes. The production Compose
  service limits total about 9.875 GiB and 5.45 CPU before the required host
  reserve, so this ticket preserves real service seams while separating phases
  that cannot provide meaningful co-resident production evidence locally.
- Decomposed into tickets 25–38 after repeated full-run failures showed that
  baseline stabilization, gate selection, resumable state, the constrained Core
  Session, product proof, three independent recovery boundaries, operational
  Health, local restore, frontend/browser proof, and final clean certification
  need separate agent-sized delivery and verification boundaries. Ticket 38 is
  the final child that unblocks this parent.
