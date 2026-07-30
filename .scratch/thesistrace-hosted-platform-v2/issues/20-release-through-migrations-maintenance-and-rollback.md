# 20 — Release through migrations, maintenance, and rollback

**What to build:** Deploy one compatible version-pinned release bundle through
explicit migrations and bounded maintenance, then recover interrupted
Activities or return to the immediately preceding compatible bundle without
silently reversing persisted state.

**Blocked by:** 15 — Dispatch P1 and P3 work fairly; 18 — Harden the Cloudflare and Caddy edge; 19 — Operate three bounded Health views.

**Status:** ready-for-agent

- [ ] One immutable release bundle pins compatible Web, Caddy, API, Worker, InsForge, Temporal, migration, and configuration versions.
- [ ] Product, InsForge, Temporal persistence, and Visibility migrations run as explicit one-shot jobs before steady services and use expand-contract compatibility.
- [ ] A failed migration leaves the prior public service authoritative or the new installation closed, never a partially upgraded public product.
- [ ] Maintenance mode stops new heavy-work admission, pauses Temporal Schedules and outbox dispatch, and allows running Activities up to 15 minutes to drain before Workers stop normally.
- [ ] An Activity interrupted by maintenance remains nonterminal for compatible redelivery and is not mislabeled cancelled, failed, or resource-exhausted.
- [ ] The immediately preceding compatible release bundle can be restored without a reverse migration; an incompatible persisted-data change is explicitly classified as restore-required.
- [ ] Service secrets are role-separated protected host-mounted files outside the repository, excluded from artifacts and telemetry, with an encrypted current recovery bundle.
- [ ] Deployment acceptance covers clean installation, forward deployment, injected migration failure, maintenance drain, node restart, and compatible rollback through the public Origin.
