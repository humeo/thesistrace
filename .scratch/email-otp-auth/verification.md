# Verification

All work ran in `.local/email-otp-auth`, branch `codex/email-otp-auth`, starting at `adc1007`. No development database or Dataset Head was reset.

- Auth quick suite: 196 tests passed. After final controller cleanup, the affected app/config tests passed again (74 tests).
- Web Auth/Operator unit tests: 103 passed. Final Auth routing/provider/account subset: 42 passed.
- Auth integration suite: 144 tests across 18 files were exercised with the repository's isolated Compose runner. The initial run had 126 passes and 18 failures. Sixteen failures came from the refactored internal credential fixture missing `Content-Type: application/json`; two came from initialization exceeding Vitest's default 5-second test limit while images were building, followed by the unfinished initialization affecting the next test. The fixture header was fixed, and the two affected files passed all 34 tests with a 30-second execution budget. The schema implementation was unchanged.
- Focused OTP, Auth HTTP and Operator Proof integration: 49 tests passed, including canonical email uniqueness, verification before account creation, concurrent/replayed/expired/exhausted codes, failed delivery cleanup, cross-origin refusal, inactive accounts, audit and Session revocation.
- Browser component acceptance: 2 tests passed at 1200px and 390px, using actual AuthProvider/AuthRoute code and intercepted test HTTP responses. Includes `returnTo`, failed delivery, wrong code, resend countdown, focus and successful bootstrap. Current screenshots are in `.local/browser-tests/results/`.
- Real product E2E: `Email verification creates one account and preserves the access lifecycle` passed. This uses the built product, real isolated PostgreSQL, Auth/Core, and the repository's Resend fake. It covers signup without an invitation, same-account login with different email case, logout/reload, deactivation/reactivation and Session revocation.
- Real Operator E2E: `Operator confirms session revocation with an emailed code` passed. It sends a code from the dialog, rejects a wrong code, consumes the correct code, revokes the target Session and preserves the Operator Session.
- Auth/Web typechecks and `git diff --check` passed. Built product bundle checks passed during E2E.

The first product E2E build exposed a TypeScript narrowing difference in the pinned container compiler; the redirect check now accepts an unknown payload explicitly. The next preflight still used the retired password login URL; the observability probe was updated to the OTP URL. Both fixes were verified in the successful product E2E. Registry connection retries recovered during the image build.

Self-review checked that public OTP delivery accepts only the sign-in purpose, Operator email is selected from the live authenticated principal, code verification uses the library's atomic consume, and exact-action proofs retain their existing transaction and session binding. Optional Operator invitations remain supported; public signup no longer depends on them. No password-login or recovery compatibility route was added.

Not run: the full Core/Agent regression, all unrelated E2E groups, or production mail-provider delivery. No real email was sent.
