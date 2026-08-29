# 03 — Invitation, credential, and access lifecycle

**Status:** complete

**Blocked by:** 01, 02

## Goal

Complete the Auth-owned invitation-only account, password, deactivation, audit,
and cleanup lifecycle using the existing Resend configuration.

## Scope

- Add Auth-owned Researcher Invitation and security-audit tables to the reviewed
  SQL snapshot and fingerprint.
- Implement canonical email, 48-hour single-use Invitation, 32-byte fragment
  token, SHA-256 storage, constant-time comparison, one-effective-Invitation
  constraint, reissue revocation, and existing-User rejection.
- Add private commands for invite, reissue, deactivate, reactivate, Session
  revoke, and display-label correction. Commands return one structured stdout
  result and never print a token or full link.
- Send Invitation synchronously through the existing Resend API and make it
  usable only after accepted delivery. Leave failed delivery unusable.
- Guard Better Auth email sign-up with Invitation and email validation. Derive
  `name` from the canonical email local-part, mark email verified, auto-login,
  and reconcile uncertain post-create Invitation consumption idempotently.
- Configure scrypt, password length 12 through 128, enumeration-safe reset,
  30-minute fragment reset links, asynchronous Resend delivery, all-Session
  reset revocation, and other-Session password-change revocation.
- Implement Deactivation and Reactivation. Deactivation revokes Sessions,
  reset records, and effective Invitations; Reactivation creates no Session.
- Record the approved audit events and keyed-HMAC unknown-email identities.
- Add daily 180-day audit, 30-day terminal Invitation/reset, expired Session,
  and rate-limit cleanup under a PostgreSQL advisory lock.
- Add a deterministic local Resend-compatible HTTP fake for Test. Production
  must reject its URL.

## Acceptance criteria

- [x] Valid Invitation creates exactly one Better Auth User and Login Session.
- [x] Expired, revoked, consumed, wrong-email, and replayed tokens cannot create
      or modify an account.
- [x] Double submit, two tabs, and lost response create one User and converge the
      Invitation to consumed without replacing the password.
- [x] Resend Invitation failure produces no usable grant and no leaked token.
- [x] Reset responses do not enumerate Users; deactivated Users receive no
      email; reset revokes all Sessions.
- [x] Deactivate/reactivate/revoke/correct commands are idempotent and audited.
- [x] Cleanup is single-owner under concurrent Auth-process attempts and emits
      no secrets or raw unknown email.

## Verification

- Fixed-clock/fixed-random Auth unit tests.
- Real-PostgreSQL concurrency and lifecycle integration tests.
- Resend fake contract tests for accepted, rejected, delayed, and unavailable
  delivery without public network access.
- Auth CLI process tests for stdout/stderr separation and secret scanning.
- `mise exec -- pnpm test` and Auth Production image smoke.

## Delivery

Use Better Auth core hooks and database constraints. Do not add the Admin or
Organization plugin, a generic Invitation framework, mail abstraction, Redis,
outbox, Cron service, or public administration route.

## Comments
