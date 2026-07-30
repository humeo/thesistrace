# 04 — Authenticate Users only through InsForge

**What to build:** Let a browser register credentials, verify email, log in,
maintain a session, and recover a password through InsForge Auth while the
ThesisTrace API accepts only verified InsForge identities and never handles a
password or creates a competing session.

**Blocked by:** 02 — Boot the Hosted Compose stack through one public Origin.

**Status:** complete

- [x] The public Origin exposes only the required InsForge registration, verification, login, session, and password-recovery routes alongside the ThesisTrace product routes.
- [x] ThesisTrace verifies InsForge JWT signature, issuer, audience, expiry, and verified-email state before accepting an authenticated product request.
- [x] Invalid, expired, unverified, or forged tokens receive sanitized stable failures and reveal no identity-mapping detail.
- [x] A valid identity that has not yet completed product provisioning receives an explicit non-provisioned product state rather than an implicit Personal Workspace.
- [x] ThesisTrace persists no password, password hash, recovery token, or parallel end-User session.
- [x] Public-Origin acceptance proves login and recovery are owned by the real InsForge Auth service rather than a mocked ThesisTrace flow.

**Acceptance evidence:** The pinned InsForge patch built successfully; Caddy 2.10.2
validated the exact route allowlist; the Public Origin completed anonymous-key
bootstrap, registration, email verification, login, current-session lookup,
strict ThesisTrace JWT acceptance, explicit `non_provisioned` state, password
recovery, and rejection of `/api/auth/config`. Focused Hosted and runtime tests:
23 passed.
