# 29 — Prove Local Identity, Isolation, and Retained Product Health

**Parent:** 24 — Deliver Hosted Local Acceptance on 2C4G.

**What to build:** Create one durable two-user product witness through the real
local Public Origin and retain it for all later stateful gates. Prove the normal
Hosted V2 product path without mixing fault injection, operational Health, or
frontend build work into this gate.

**Blocked by:** 28 — Establish a Reusable Constrained Hosted Core Session.

**Status:** ready-for-agent

- [ ] The gate reuses the staged Core Session and refuses to start, reset, rebuild, or replace its release and infrastructure.
- [ ] Two acceptance Users complete invitation-mode admission, InsForge verification, login, password recovery, and idempotent provisioning of exactly one private Personal Workspace each through the real local Public Origin.
- [ ] A bounded shared Dataset is published and readable by both Users while private research, run, result, DailyTrack, and deletion resources remain non-disclosing and non-writable across Workspace boundaries.
- [ ] User A creates and completes one real ResearchRun, inspects its result, exercises quota and idempotent rerun behavior, activates and advances one DailyTrack, and stops it through production API and Temporal paths.
- [ ] Equivalence evidence is captured and retained before deletion. Tombstone behavior is proved on a separate disposable terminal resource so it cannot erase the witness required by downstream recovery gates.
- [ ] Raw, nested, and signed Storage access is denied through the Public Origin, while the supported bounded product read path still succeeds.
- [ ] Stable opaque identifiers and post-state digests for both Users, Workspaces, Dataset, ResearchRun, result, DailyTrack, and equivalence witness are recorded for downstream gates; secrets and tokens are not recorded, and each stateful step reacquires authentication.
- [ ] Re-running the gate in the same compatible state is idempotent, introduces no duplicate domain resources, and makes no fault-injection, physical-capacity, production-launch, or production-recovery claim.
