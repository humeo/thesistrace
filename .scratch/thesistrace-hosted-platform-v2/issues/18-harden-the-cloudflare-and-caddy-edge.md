# 18 — Harden the Cloudflare and Caddy edge

**What to build:** Expose the Hosted product through one Cloudflare-proxied
browser Origin, reject direct-origin and forged-proxy traffic, and apply abuse
limits at the layer that possesses the required identity.

**Blocked by:** 05 — Consume an invitation and provision one Personal Workspace; 06 — Isolate private research and share read-only Datasets; 08 — Recover, cancel, and fence Research Workflows; 12 — Advance DailyTrack through finite Workflows; 17 — Delete terminal resources through Tombstones.

**Status:** ready-for-agent

- [ ] Cloudflare is the external public edge, uses Full (strict) origin TLS, and the origin firewall accepts Web traffic only from verified Cloudflare proxy ranges.
- [ ] Direct-origin requests and forwarding metadata from untrusted sources are rejected rather than treated as authenticated edge traffic.
- [ ] Caddy serves the production Web and proxies only the versioned ThesisTrace API and required public InsForge Auth routes; it never exposes InsForge Storage or an administration route.
- [ ] PostgreSQL, Storage, Temporal, Workers, dashboards, metrics, and Operator endpoints have no public listener or edge route.
- [ ] Cloudflare applies coarse client-IP limits to registration, login, verification, and recovery, while the API applies short-window User and Personal Workspace limits to authenticated product routes.
- [ ] Rate limits return `429` with sanitized semantics and remain distinguishable from durable-work quotas and disk-pressure admission.
- [ ] Security acceptance proves no raw artifact, manifest-object, signed URL, public bucket operation, object key, or filesystem path is reachable through the Origin.
