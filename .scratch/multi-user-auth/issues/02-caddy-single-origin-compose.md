# 02 — Caddy single-origin Compose topology

**Status:** ready-for-agent

**Blocked by:** 01

## Goal

Replace Nginx with Caddy and make the canonical Compose graph expose Vite,
Better Auth, and FastAPI through one browser origin without changing API paths.

## Scope

- Replace the Web runtime stage with pinned `caddy:2-alpine`, serve the built
  Vite assets from `/srv`, add the repository Caddyfile, and delete the Nginx
  template.
- Route mutually exclusive `handle /api/auth/*`, `handle /api/*`, and static
  fallback groups in that order. Never use `handle_path` for either API.
- Explicitly reject Auth internal and all backend health paths at the public
  gateway.
- Add Auth and `auth-initialize` to base Compose and preserve independent Core
  and Auth initialization and runtime identities.
- Add a Production overlay that publishes only Caddy 80 and 443, persists
  Caddy `/data`, and uses automatic HTTPS. Keep all other services private.
- Keep Development and Test on the same Caddy graph over loopback HTTP. Retain
  only explicitly justified loopback diagnostic ports.
- Drive the site address, Better Auth base URL, Core Origin, and email URL base
  from exact `THESISTRACE_PUBLIC_ORIGIN`.
- Remove Caddy startup dependencies on Auth and Core so static unavailable and
  retry states remain renderable.
- Implement no-cache Auth/API/SPA fallback and immutable hashed-asset caching.

## Acceptance criteria

- [ ] A browser reaches static Web, `/api/auth/ok`, and `/api/data` only through
      one Caddy origin with original paths preserved.
- [ ] SPA refresh works for all existing product and future Auth routes.
- [ ] Caddy remains healthy and serves static files while Auth or Core is down.
- [ ] Production Compose exposes exactly 80 and 443 from Caddy and no host port
      for Auth, Core, PostgreSQL, RustFS, or Workers.
- [ ] HTTP redirects to HTTPS in Production and certificate state survives a
      Caddy container restart.
- [ ] `deploy/core/nginx.conf.template` and all Nginx image/config assertions are
      removed rather than retained as alternatives.

## Verification

- Caddy configuration validation inside the final Web image.
- Compose configuration tests for route order, service dependency direction,
  volumes, origin propagation, and negative host bindings.
- Development/Test HTTP smoke and isolated Production HTTPS image smoke.
- Update architecture tests that currently assert Nginx and absence of Auth or
  Caddy, then run `mise exec -- pnpm test`.

## Delivery

One Caddy topology replaces Nginx outright. Do not preserve a second Web image,
direct browser API origin, or Nginx compatibility file.

## Comments
