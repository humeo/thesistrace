# Public landing and email OTP integration

The approved QuantTrace landing direction is now the public `/` route. It mounts without AuthProvider, defaults to English, preserves language in the URL, and links to `/login`. Styles are scoped to `.landing-page`; prototype variant controls and prototype-only footer copy are excluded. Brand asset is shared with the OTP login page. Source reference: `codex/landing-prototype` at `ce2f997`.

Merged `codex/email-otp-auth` onto main base `ae30735` in an isolated checkout. Resolved the obsolete public password fixture conflict by keeping the internal credential harness; updated the OTP test dependency for the current quota policy interface.

Verification before merge:
- Auth/Web typechecks passed.
- Auth app/config: 75 tests passed.
- Public landing and OTP browser flows: 4 passed at desktop/mobile widths; after CSS isolation correction, the two landing cases passed again. Actual in-app browser screenshot reviewed.
- Product Vite build and bundle budget passed (26 assets, 1,998,981 bytes).
- Auth integration: 54/55 passed initially; the audit-failure rollback case hit a client query timeout. A separate rerun failed before tests because PostgreSQL initialization exceeded the runner's 20-second bound. Container evidence confirms it was still initializing. A focused run of the rollback case then passed (1 test). This does not establish the root cause of the first transient timeout; preserve the initial evidence.
- Logs: `/private/tmp/landing-auth-integration.txt`, `/private/tmp/landing-auth-recheck.txt`, `/private/tmp/landing-auth-target.txt`, `/private/tmp/landing-browser-final.txt`, `/private/tmp/landing-build.txt`.

No production deployment or real email delivery was performed. Main contains unrelated uncommitted parallel work, which must be preserved during merge. Destination checks will be recorded after merge.

Destination `main` at `f35f66a`: Auth/Web typechecks passed; Auth unit tests 75/75, isolated integration tests 55/55, browser tests 4/4 passed. Logs: `/private/tmp/main-landing-{unit,auth,browser}.txt`. All pre-existing tracked edits were verified by content hash, and the parallel styles diff hunks were verified unchanged after restoration. The initial integration timeout remains recorded above; no production timeout setting was relaxed.
