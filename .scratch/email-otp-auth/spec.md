# Email OTP access

Status: complete

Public access uses email then a six-digit verification code. First verification creates a Researcher; later verification signs into the same Researcher. Canonical email is unique in PostgreSQL. Codes expire in five minutes, allow three attempts, and can be consumed once. Inactive Researchers cannot sign in. Password sign-in and recovery are removed from the public product flow. Operator confirmation uses a separate email-verification code; it retains the exact-action, one-session, one-time proof.

Verification: isolated PostgreSQL integration tests for registration, existing/canonical email, replay/concurrency, attempts, expiry, inactive users and delivery failure; web typecheck and browser flow.

Operator-issued invitations remain an optional provisioning channel. They are not required for public registration. No password-login or password-recovery compatibility endpoint is exposed.

Implemented in `47c3555`. Acceptance evidence: [verification](verification.md).
