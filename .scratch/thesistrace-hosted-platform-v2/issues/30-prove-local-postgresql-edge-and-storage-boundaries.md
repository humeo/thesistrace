# 30 — Prove Local PostgreSQL, Edge, and Storage Boundaries

**Parent:** 24 — Deliver Hosted Local Acceptance on 2C4G.

**What to build:** Prove the security and admission boundaries that are cheaper
and clearer outside the long product workflow. Exercise current production
migrations, service roles, edge policy, and storage enforcement with isolated
probes that leave the reusable Core Session compatible.

**Blocked by:** 28 — Establish a Reusable Constrained Hosted Core Session.

**Status:** ready-for-agent

- [ ] A gate-owned disposable PostgreSQL database applies the current production migration sequence and enumerates every relation containing `workspace_id`; the inventory fails closed when a new relation lacks an explicit isolation test or exemption.
- [ ] Every workspace-scoped table rejects or non-disclosingly empties cross-Workspace reads and writes, missing transaction context, forged context, and direct use through each production service role; tests distinguish authorization denial from accidental empty fixtures.
- [ ] Edge probes cover authentication, request-size and rate admission, trusted forwarding, and denial of raw, nested, encoded, traversal, and signed `/storage/*` variants while supported Public Origin product routes remain usable.
- [ ] Storage, Working Cache, container/network, credential, disk/object admission, cancellation, and late-result fencing checks use the actual production implementations and include the previously observed cross-UID cache case.
- [ ] Required OpenTelemetry and audit records contain the expected bounded identifiers and outcome classifications without tokens, credentials, raw prompts, private research payloads, or unbounded labels.
- [ ] Every sub-boundary writes a separate result so a failure identifies the exact table, role, route, encoding, or policy assertion rather than failing one aggregate security check.
- [ ] Cleanup targets only gate-owned fixtures and restores the Core Session to its recorded input state digest; any unexpected shared-state mutation invalidates the session instead of being hidden.
