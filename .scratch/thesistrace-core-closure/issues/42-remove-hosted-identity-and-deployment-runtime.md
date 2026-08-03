# 42 — Remove Hosted identity and deployment runtime

**What to build:** Delete inactive login, tenant, and hosted-deployment runtime
code while retaining deferred identity and deployment decisions as history.

**Blocked by:** 39, 41.

**Status:** ready-for-agent

- [ ] The Hosted archive ref is reverified before deletion.
- [ ] InsForge authentication integration, Auth Session runtime, User,
  Personal Workspace, invitation, tenancy, and RLS enforcement code are removed
  from the active product.
- [ ] Hosted deployment runtime, Cloudflare, Caddy, hosted Compose, rollout, and
  release-migration machinery are removed with their active targets and tests.
- [ ] Core resource shapes, URLs, and actions retain no ownership or identity
  placeholder branch.
- [ ] ADR and research history remain available; deferred identity material is
  clearly not an active Core requirement.
- [ ] Core still starts as one instance-owned product without login.

**How to verify:**

- Run `uv run pytest -q tests/architecture tests/integration tests/acceptance`
  and `bun run --cwd web test:e2e` with no InsForge or deployment service.
- Inspect active dependencies, entrypoints, and configuration; none may require
  an identity, tenant, reverse proxy, or hosted deployment setting.

## Comments
