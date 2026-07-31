# 20 — Release through migrations, maintenance, and rollback

**What to build:** Deploy one compatible version-pinned release bundle through
explicit migrations and bounded maintenance, then recover interrupted
Activities or return to the immediately preceding compatible bundle without
silently reversing persisted state.

**Blocked by:** 15 — Dispatch P1 and P3 work fairly; 18 — Harden the Cloudflare and Caddy edge; 19 — Operate three bounded Health views.

**Status:** resolved

- [x] One immutable release bundle pins compatible Web, Caddy, API, Worker, InsForge, Temporal, migration, and configuration versions.
- [x] Product, InsForge, Temporal persistence, and Visibility migrations run as explicit one-shot jobs before steady services and use expand-contract compatibility.
- [x] A failed migration leaves the prior public service authoritative or the new installation closed, never a partially upgraded public product.
- [x] Maintenance mode stops new heavy-work admission, pauses Temporal Schedules and outbox dispatch, and allows running Activities up to 15 minutes to drain before Workers stop normally.
- [x] An Activity interrupted by maintenance remains nonterminal for compatible redelivery and is not mislabeled cancelled, failed, or resource-exhausted.
- [x] The immediately preceding compatible release bundle can be restored without a reverse migration; an incompatible persisted-data change is explicitly classified as restore-required.
- [x] Service secrets are role-separated protected host-mounted files outside the repository, excluded from artifacts and telemetry, with an encrypted current recovery bundle.
- [x] Deployment acceptance covers clean installation, forward deployment, injected migration failure, maintenance drain, node restart, and compatible rollback through the public Origin.

## Comments

- Added content-addressed Release Bundles with candidate/current/previous
  pointers, Bundle-ID-tagged custom images whose exact image IDs participate
  in that final Bundle ID, explicit one-shot migration and
  release-gate phases, expand-contract compatibility epochs, and rollback that
  never runs a reverse migration. Existing `up` and `restart` operations cannot
  rebuild an active immutable bundle; changed source must use `deploy`.
- Added maintenance admission and relay gates, Temporal Schedule pause/resume,
  bounded Activity drain, normal Worker stop, and nonterminal redelivery
  semantics for interrupted work.
- Added role-separated mode-600 secret files and an AES-GCM encrypted recovery
  bundle. The production runbook requires Hosted state and the recovery
  passphrase to live outside the repository and separately from each other.
- Automated verification passed the focused release/Compose tests, Ruff, the
  full Python suite (`289 passed, 15 skipped`), Web typecheck/build, and both
  narrow and desktop Playwright product chains. The E2E expectation was
  decoupled from the physical Parquet partition count after it exposed a stale
  pre-partitioning object-count assertion.
- Follow-up Spec and Standards reviews passed after binding the final Bundle ID
  to both source content and exact built image IDs, giving every finalized
  Bundle its own immutable image tags and deriving all image operations from
  the Bundle manifest instead of duplicated shell lists.
- Live Compose acceptance proved clean startup, forward deployment, a staged
  candidate whose injected migration failure left the previous public bundle
  authoritative under maintenance, successful retry, 15-minute maintenance
  semantics, node restart, encrypted/role-separated secrets, compatible
  rollback, and public-Origin smoke. Docker Desktop exhausted regenerable build
  cache during repeated acceptance; only builder cache and unreferenced images
  were pruned, never volumes or persisted product data, and Temporal PostgreSQL
  recovered automatically.
- Final live regression acceptance used current Bundle
  `0.1.0-1f0199b75441b7db` and previous Bundle
  `0.1.0-10894737a5e18a10`: rollback in both directions restored the exact
  locked image IDs and passed public-Origin smoke. A fresh injected migration
  failure left the current pointer unchanged and maintenance enabled; explicit
  recovery exited maintenance and passed smoke again.
