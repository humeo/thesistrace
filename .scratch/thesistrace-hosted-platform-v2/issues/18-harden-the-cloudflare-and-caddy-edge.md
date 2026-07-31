# 18 — Harden the Cloudflare and Caddy edge

**What to build:** Expose the Hosted product through one Cloudflare-proxied
browser Origin, reject direct-origin and forged-proxy traffic, and apply abuse
limits at the layer that possesses the required identity.

**Blocked by:** 05 — Consume an invitation and provision one Personal Workspace; 06 — Isolate private research and share read-only Datasets; 08 — Recover, cancel, and fence Research Workflows; 12 — Advance DailyTrack through finite Workflows; 17 — Delete terminal resources through Tombstones.

**Status:** resolved

- [x] Cloudflare is the external public edge, uses Full (strict) origin TLS, and the origin firewall accepts Web traffic only from verified Cloudflare proxy ranges.
- [x] Direct-origin requests and forwarding metadata from untrusted sources are rejected rather than treated as authenticated edge traffic.
- [x] Caddy serves the production Web and proxies only the versioned ThesisTrace API and required public InsForge Auth routes; it never exposes InsForge Storage or an administration route.
- [x] PostgreSQL, Storage, Temporal, Workers, dashboards, metrics, and Operator endpoints have no public listener or edge route.
- [x] Cloudflare applies coarse client-IP limits to registration, login, verification, and recovery, while the API applies short-window User and Personal Workspace limits to authenticated product routes.
- [x] Rate limits return `429` with sanitized semantics and remain distinguishable from durable-work quotas and disk-pressure admission.
- [x] Security acceptance proves no raw artifact, manifest-object, signed URL, public bucket operation, object key, or filesystem path is reachable through the Origin.

## Resolution

- Added one canonical Cloudflare range contract with exact-set startup
  validation, Full (strict) origin TLS material boundary, host-input and Docker
  DNAT-forward nftables policy, strict Caddy proxy parsing, direct peer
  rejection, explicit private-path denial, and unauthenticated Auth-route WAF
  rate-limit declaration.
- Added bounded authenticated User and Personal Workspace request windows in
  the API with a stricter state-changing limit and sanitized `429` responses.
- Kept Caddy capability-free under `cap_drop: ALL` by listening on unprivileged
  container ports while publishing only host ports 80 and 443.
- Preserved every already-committed migration byte-for-byte; a stale local
  development ledger created from a pre-commit `0010` intermediate was repaired
  explicitly rather than weakening the production checksum gate.
- Verification: full backend suite (`234 passed, 14 skipped`), Ruff, Caddy
  container build/start, public-Origin smoke, live `404` checks for Storage,
  object, and Auth-administration paths, and an ephemeral direct-origin probe
  returning `403`.
