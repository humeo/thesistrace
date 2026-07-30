# 23 — Prove the Hosted V2 release boundary

**What to build:** Deliver one release-grade black-box acceptance and Operator
runbook proving that Hosted V2 preserves the complete V1 research chain while
enforcing identity, isolation, admission, execution, storage, deployment, and
recovery boundaries through the real production-like stack.

**Blocked by:** 18 — Harden the Cloudflare and Caddy edge; 20 — Release through migrations, maintenance, and rollback; 21 — Back up and restore the coordinated platform; 22 — Qualify the single-node capacity envelope; `thesistrace-v1-research-platform/28 — Prove the revised V1 product chain`.

**Status:** ready-for-agent

- [ ] A clean-stack Public-Origin test covers authorization-gated invitation issuance, InsForge registration and verification, login, password recovery, idempotent provisioning, and exactly one Personal Workspace.
- [ ] Two real Users prove non-disclosing cross-Workspace denial for list, read, create, update, run, result, cancel, rerun, activate, advance, verify, stop, and delete operations using valid identifiers from the other Workspace.
- [ ] The same test proves shared read-only Dataset Releases, bounded product result and time-series views, quota failures, Tombstone deletion, and complete absence of raw or signed Storage access.
- [ ] Recovery scenarios interrupt API, outbox relay, Temporal Worker, Activity, publication, maintenance, and node execution boundaries and prove no duplicate domain result or partial authoritative artifact.
- [ ] After every final migration, the real PostgreSQL RLS seam enumerates every table with `workspace_id` and tests cross-Workspace direct reads and writes plus missing and forged transaction context through every production service role.
- [ ] The release gate also exercises the real Temporal deterministic-dispatch seam; mock-only policy or scheduler tests are insufficient.
- [ ] A resource-exhaustion matrix covers ResearchRun, Dataset Publication, Tracking Advance, Equivalence, and Generation rebuild and proves at most two executions, stable classification, and no partial authoritative result.
- [ ] Launch remains closed unless source authorization, migration, direct-origin security, capacity, coordinated backup, full restore, and three-plane health evidence all pass.
- [ ] The Operator runbook documents installation, secrets, authorization declaration, invitation management, Dataset Publication, quota overrides, maintenance, rollback, daily dashboard inspection, backup, restore, and the absence of alert-delivery and high-availability guarantees.
- [ ] Final backend, frontend, browser, RLS, Temporal, security, storage, capacity, deployment, and recovery suites pass from a clean checkout with no unresolved in-scope review finding.
