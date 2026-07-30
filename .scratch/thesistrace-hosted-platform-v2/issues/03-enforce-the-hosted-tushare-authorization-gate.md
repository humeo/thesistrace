# 03 — Enforce the Hosted Tushare authorization gate

**What to build:** Give the Operator an audited way to record the upstream
authorization declaration required for hosted shared Tushare use, and keep live
Dataset Publication and invited-user launch closed until that declaration
exists.

**Blocked by:** 02 — Boot the Hosted Compose stack through one public Origin.

**Status:** ready-for-agent

- [ ] The versioned Operator CLI can record and inspect a source-authorization declaration with its actor, time, intended hosted-use scope, and audit identity without storing credential material in the audit event.
- [ ] Without an accepted declaration, live Tushare Dataset Publication fails with `SOURCE_AUTHORIZATION_REQUIRED` even when a valid Tushare token is configured.
- [ ] Deterministic fixture Dataset Publication and fixture acceptance remain available while the authorization gate is closed.
- [ ] Recording the declaration enables the hosted-use policy gate but does not itself validate, negotiate, or interpret upstream legal rights.
- [ ] Every successful and rejected state-changing CLI invocation appends a sanitized, non-deletable management audit event.
- [ ] The authorization state is durable across API, CLI, and node restarts and is available to the later Registration Invitation admission path.
