# 05 — Consume an invitation and provision one Personal Workspace

**What to build:** Let an invited, email-verified identity atomically become one
ThesisTrace User with exactly one Personal Workspace, while the Operator retains
a narrow audited CLI for issuing and revoking Registration Invitations.

**Blocked by:** 03 — Enforce the Hosted Tushare authorization gate; 04 — Authenticate Users only through InsForge.

**Status:** ready-for-agent

- [ ] The Operator CLI issues a single-use invitation for one normalized email with an explicit future expiry, and rejects issuance while the hosted Tushare authorization gate is closed.
- [ ] The Operator can revoke an unused invitation, and issue, revoke, expire, consume, and failed-consumption outcomes are represented by sanitized management audit events.
- [ ] Only a verified InsForge identity whose normalized email matches one issued, unexpired, unrevoked invitation can complete product provisioning.
- [ ] One PostgreSQL transaction consumes the invitation, creates or resolves the ThesisTrace User, creates or resolves exactly one Personal Workspace, and records the audit event.
- [ ] A failure before the local transaction commits leaves the invitation issued and retryable and leaves no partial User, Personal Workspace, or consumption audit fact.
- [ ] If the local transaction commits but the response is lost, retrying returns the same User, Personal Workspace, and consumed invitation without creating duplicates.
- [ ] Two concurrent consumers of one invitation produce exactly one winning provisioning result.
- [ ] Invitation state no longer affects login or InsForge password recovery after successful provisioning, and public self-service Personal Workspace creation remains unavailable.
