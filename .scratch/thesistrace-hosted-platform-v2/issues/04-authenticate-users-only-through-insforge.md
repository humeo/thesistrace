# 04 — Authenticate Users only through InsForge

**What to build:** Let a browser register credentials, verify email, log in,
maintain a session, and recover a password through InsForge Auth while the
ThesisTrace API accepts only verified InsForge identities and never handles a
password or creates a competing session.

**Blocked by:** 02 — Boot the Hosted Compose stack through one public Origin.

**Status:** ready-for-agent

- [ ] The public Origin exposes only the required InsForge registration, verification, login, session, and password-recovery routes alongside the ThesisTrace product routes.
- [ ] ThesisTrace verifies InsForge JWT signature, issuer, audience, expiry, and verified-email state before accepting an authenticated product request.
- [ ] Invalid, expired, unverified, or forged tokens receive sanitized stable failures and reveal no identity-mapping detail.
- [ ] A valid identity that has not yet completed product provisioning receives an explicit non-provisioned product state rather than an implicit Personal Workspace.
- [ ] ThesisTrace persists no password, password hash, recovery token, or parallel end-User session.
- [ ] Public-Origin acceptance proves login and recovery are owned by the real InsForge Auth service rather than a mocked ThesisTrace flow.
