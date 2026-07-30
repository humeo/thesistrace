# 05 — Consume an invitation and provision one Personal Workspace

**What to build:** Let an invited, email-verified identity atomically become one
ThesisTrace User with exactly one Personal Workspace, while the Operator retains
a narrow audited CLI for issuing and revoking Registration Invitations.

**Blocked by:** 03 — Enforce the Hosted Tushare authorization gate; 04 — Authenticate Users only through InsForge.

**Status:** complete

- [x] The Operator CLI issues a single-use invitation for one normalized email with an explicit future expiry, and rejects issuance while the hosted Tushare authorization gate is closed.
- [x] The Operator can revoke an unused invitation, and issue, revoke, expire, consume, and failed-consumption outcomes are represented by sanitized management audit events.
- [x] Only a verified InsForge identity whose normalized email matches one issued, unexpired, unrevoked invitation can complete product provisioning.
- [x] One PostgreSQL transaction consumes the invitation, creates or resolves the ThesisTrace User, creates or resolves exactly one Personal Workspace, and records the audit event.
- [x] A failure before the local transaction commits leaves the invitation issued and retryable and leaves no partial User, Personal Workspace, or consumption audit fact.
- [x] If the local transaction commits but the response is lost, retrying returns the same User, Personal Workspace, and consumed invitation without creating duplicates.
- [x] Two concurrent consumers of one invitation produce exactly one winning provisioning result.
- [x] Invitation state no longer affects login or InsForge password recovery after successful provisioning, and public self-service Personal Workspace creation remains unavailable.

**Acceptance evidence:** Operator, API, schema, authorization, and sanitization
tests passed locally (13 passed, 3 PostgreSQL-only tests skipped). The same
PostgreSQL acceptance file then passed all 10 tests against the real Hosted
PostgreSQL service, including concurrent provisioning, injected pre-commit
rollback and retry, one-Workspace constraints, expiry, revocation, and sanitized
failed-consumption audit facts. Ruff passed on every touched Python file.
