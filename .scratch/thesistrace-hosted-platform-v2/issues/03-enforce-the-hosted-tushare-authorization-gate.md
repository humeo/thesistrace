# 03 — Enforce the Hosted Tushare authorization gate

**What to build:** Give the Operator an audited way to record the upstream
authorization declaration required for hosted shared Tushare use, and keep live
Dataset Publication and invited-user launch closed until that declaration
exists.

**Blocked by:** 02 — Boot the Hosted Compose stack through one public Origin.

**Status:** resolved

- [x] The versioned Operator CLI can record and inspect a source-authorization declaration with its actor, time, intended hosted-use scope, and audit identity without storing credential material in the audit event.
- [x] Without an accepted declaration, live Tushare Dataset Publication fails with `SOURCE_AUTHORIZATION_REQUIRED` even when a valid Tushare token is configured.
- [x] Deterministic fixture Dataset Publication and fixture acceptance remain available while the authorization gate is closed.
- [x] Recording the declaration enables the hosted-use policy gate but does not itself validate, negotiate, or interpret upstream legal rights.
- [x] Every successful and rejected state-changing CLI invocation appends a sanitized, non-deletable management audit event.
- [x] The authorization state is durable across API, CLI, and node restarts and is available to the later Registration Invitation admission path.

## Comments

- Added `thesistrace-operator source-authorization record|inspect` with one fixed
  hosted-use scope and no credential input.
- Local acceptance proves a configured token alone is rejected while fixture
  publication remains available; invalid raw scope input is not retained in
  the rejected audit event.
- Real PostgreSQL acceptance observed the public API transition from
  `SOURCE_AUTHORIZATION_REQUIRED` to `TOKEN_MISSING` after the CLI declaration,
  proving the policy gate changed independently of source credentials.
- Successful and rejected PostgreSQL audit rows were recorded, direct deletion
  was rejected by the immutable-history trigger, and the same declaration was
  returned by both CLI and API after a complete Compose restart.
