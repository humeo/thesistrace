# 06 — Cross-stack security and Production qualification

**Status:** ready-for-agent

**Blocked by:** 05

## Goal

Close the multi-user feature with gateway hardening, full two-Researcher
acceptance, Production environment validation, and final-image proof.

## Scope

- Apply the approved Caddy CSP, no-referrer, nosniff, frame/object/base denial,
  Permissions Policy, cache policy, and Production-only one-year HSTS without
  preload or `includeSubDomains`.
- Overwrite one trusted client-IP header at Caddy and configure Auth to trust
  only it. Sanitize Caddy/Hono/FastAPI logs to method, normalized path, status,
  duration, request ID, and approved context.
- Complete the deployment-side access command that reports Core-owned active
  DailyTrack count and then performs Auth-owned Deactivation without cross-schema
  grants or automatic Stop.
- Add the repository-external mode-0600 Production environment contract and
  validate Auth secret, database passwords, Resend key, public origin, schema,
  and Production rejection of the Test mail fake.
- Implement and test hard Auth-secret rotation as Session, Invitation, and reset
  invalidation with no old-key ring.
- Give all single-node services one replica and `restart: unless-stopped` while
  making no availability claim.
- Extend all browser, integration, Compose, and Production Image Smoke gates to
  the final single-origin topology and two-Researcher security matrix.
- Update current runbooks and architecture status only after the final images
  pass; remove transitional assertions and notes instead of preserving them.

## Acceptance criteria

- [ ] Final browser acceptance covers Invitation success/replay/expiry/reissue,
      login/logout/reset/change password, revoke/deactivate/reactivate, Session
      refresh, bootstrap retry, and Auth unavailable.
- [ ] A two-Researcher matrix proves Folder, Run, Batch, Track, receipt, cursor,
      and Draft isolation and same local system Folder IDs.
- [ ] Chart, Alpha editor, and all Auth forms work under the final CSP with no
      unexpected policy violation.
- [ ] Production publishes only Caddy 80/443; HTTP redirects to HTTPS; private
      Auth/Core health and internal verifier paths are unreachable publicly.
- [ ] Caddy serves static unavailable UI when Auth or Core is down, while Core
      and Auth report their agreed liveness/readiness independently.
- [ ] Secret, Cookie, token, raw unknown email, email link, body, query, Formula,
      object key, and manifest scans are clean across every container log and
      saved failure artifact.
- [ ] Production rejects placeholder or Test configuration before serving Auth.
- [ ] Final docs describe implemented current behavior without target caveats.

## Verification

- `mise exec -- pnpm test`
- `mise exec -- pnpm test:integration`
- `mise exec -- pnpm test:e2e`
- `mise exec -- pnpm test:image-smoke`
- `mise exec -- pnpm test:benchmark`
- `mise exec -- pnpm check:release`

Capture on failure: service logs, exit codes, request/response status without
secrets, Compose config, image IDs, CSP console errors, screenshots, and the
fixed test seed.

## Delivery

This is the feature final gate and its own commit. Production backup/restore,
HA, managed ingress, Vault, OAuth, MFA, Organizations, and migration remain
explicitly outside the ticket.

## Comments
