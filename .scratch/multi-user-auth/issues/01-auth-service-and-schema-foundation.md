# 01 — Auth service and exact schema foundation

**Status:** complete

**Blocked by:** none

## Goal

Add a fail-closed TypeScript Auth service that owns Better Auth, its exact
PostgreSQL schema, database-backed Login Sessions, and a narrow private Session
verification contract without changing the existing Core product flow yet.

## Scope

- Add `auth/` as a pnpm workspace using Node 24, Hono, Better Auth, PostgreSQL,
  and exact dependency versions.
- Mount Better Auth at `/api/auth/*` before any Hono catch-all.
- Configure email/password, UUID User IDs, canonical email, the minimal `active`
  User field, seven-day rolling Sessions, one-day update age, database rate
  limits, exact trusted origin, CSRF checks, and disabled Cookie Session cache.
- Keep account creation fail-closed until Invitation validation lands: every
  email sign-up attempt without a recognized Invitation context is rejected.
- Add Auth liveness and readiness. Readiness checks only Auth database access,
  exact schema fingerprint, and Session storage.
- Add one private Session verifier that accepts the original Cookie, forces a
  Better Auth database lookup with refresh disabled, rejects inactive Users,
  and returns only Researcher ID, email, display label, and active state.
- Generate, review, normalize, and commit the complete Better Auth SQL snapshot.
  Add `auth-initialize` with empty-scope initialization and exact fingerprint
  verification; never call Better Auth migration APIs at runtime.
- Establish `thesistrace_owner`, `core_runtime`, and `auth_runtime` grants with
  tests proving zero cross-schema runtime privileges.
- Validate `THESISTRACE_PUBLIC_ORIGIN`, Auth database URL, and
  `BETTER_AUTH_SECRET`; reject Production placeholders and invalid origins.

## Acceptance criteria

- [x] `/api/auth/ok` succeeds against an initialized isolated Auth database.
- [x] Missing, partial, extra, or fingerprint-mismatched Auth schema terminates
      initializer or runtime with a sanitized error.
- [x] The private verifier distinguishes valid, invalid, expired, revoked,
      inactive, and malformed Session state without setting a Cookie.
- [x] Auth cannot select from a Core product table and Core cannot select from an
      Auth table under their runtime roles.
- [x] No JWT, bearer, Admin, Organization, API-key, MFA, passkey, or Cookie-cache
      plugin/configuration is present.
- [x] Auth logs contain no Cookie, credential, token, request body, or full URL.

## Verification

- Auth unit tests for configuration and origin validation.
- Real-PostgreSQL integration tests for schema initialization, fingerprint,
  role isolation, Session expiry/update, revocation, active state, and private
  verifier responses.
- Production Auth image build and startup smoke with valid and invalid config.
- `mise exec -- pnpm test` remains green.

## Delivery

Commit only this accepted foundation. Do not add an unguarded temporary signup
path, in-memory production rate limit, runtime migration, or Core fallback.

## Comments
