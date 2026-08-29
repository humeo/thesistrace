# 02 — Secure Invitation mutations with Operator Proof

**What to build:** Let the Operator issue and reissue Researcher Invitations from
the Console only after confirming the current password, with each authorized
mutation bound to one exact request and unusable afterward.

**Blocked by:** 01 — Establish the singleton Operator and read-only Console.

**Status:** complete

- [x] Every Invitation mutation opens an accessible confirmation dialog showing
  the action, target email, and effect before requesting the current password.
- [x] Successful password confirmation produces an Operator Proof valid for 60
  seconds and one successful consumption, bound to the current Login Session,
  operation name, and canonical exact request content.
- [x] Issuing an Invitation uses the existing canonical-email, admission,
  delivery, expiry, and invite-only account rules and refreshes the visible
  Invitation state after success.
- [x] Reissuing an Invitation clearly warns that the old link will become invalid
  and atomically leaves exactly one effective Invitation when delivery succeeds.
- [x] Failed validation, delivery failure, invalid password, proof expiry,
  request mismatch, Session mismatch, concurrent duplicate consumption, and
  replay produce no unauthorized mutation and preserve the prior effective
  Invitation.
- [x] The browser never persists or forwards the current password beyond the Auth
  confirmation request, and the password is cleared when the dialog closes or
  completes.
- [x] Ordinary Researchers receive `404` from proof and Invitation mutation APIs.
- [x] Auth unit and isolated real-PostgreSQL integration tests cover exact proof
  binding, expiry, single consumption, concurrency, replay, issue, reissue, and
  delivery failure without implementation-detail assertions.
- [x] A real browser test through Caddy proves issue, reissue, old-link
  invalidation, keyboard operation, Escape behavior, and focus restoration.

## Implementation Plan

1. **Persist one fail-closed Auth proof lifecycle.** Add an
   `auth.operator_proof` snapshot table containing only an opaque-token hash,
   Login Session, operation, canonical request hash, 60-second expiry, and
   available/claimed/consumed timestamps. Session deletion cascades its proofs;
   daily cleanup removes expired rows. The schema remains an exact empty-scope
   snapshot with no migration or compatibility path.
2. **Confirm the current credential inside the singleton boundary.** Add an Auth
   proof service that locks the current Operator Assignment, active Researcher,
   Login Session, and Better Auth credential row while verifying the password
   with Better Auth's configured verifier. A same-origin rate-limited endpoint
   accepts exactly operation, target email, and password, canonicalizes the
   email, rechecks Operator authority, and returns only a random opaque proof and
   expiry. Ordinary Researchers continue to receive an empty `404`.
3. **Claim before side effects and consume only with successful mutation.** Bind
   each proof to `invitation.issue` or `invitation.reissue` plus the canonical
   email request hash. Claim it atomically before delivery so concurrent replay
   cannot send or mutate twice. Consume the claim in the same Auth transaction
   that makes the delivered Invitation effective; release it after a rejected
   request or delivery failure when still unexpired. Expiry, token mismatch,
   Session mismatch, request mismatch, consumed proof, or concurrent claim all
   fail closed.
4. **Make reissue preserve the old effective link until replacement succeeds.**
   Extend the existing shared Invitation service with an internal
   replacement-pending state excluded from the effective-email unique index.
   Delivery success atomically revokes the old Invitation and promotes the new
   one; delivery failure terminals only the replacement and leaves the old link
   valid. Private CLI and Console continue to call this one service.
5. **Add the accessible Console mutation flow.** Add an Invite Researcher action
   and per-email Reissue action to the existing dense Invitation surface. Both
   open the same native modal dialog with explicit action, canonical target,
   effect, current-password field, status text, keyboard containment, Escape,
   and trigger-focus restoration. The browser sends the password only to proof
   confirmation, clears it before forwarding the proof, keeps the proof only in
   the active call, and reloads directory state after success.
6. **Qualify the security invariants at real seams.** Drive proof and Invitation
   changes with unit and isolated PostgreSQL tests for password rejection,
   binding, expiry, Session mismatch, replay, concurrent claim, delivery
   failure, and atomic replacement. Extend HTTP contract tests for origin,
   sanitized errors, and ordinary `404`; extend the real Caddy browser flow for
   issue, reissue, old-token invalidation, keyboard submit, Escape, focus
   restoration, and password non-forwarding. Run host, Auth integration, E2E,
   and Production Caddy gates, then complete the required Standards and Spec
   review/fix/re-review cycle before this ticket's independent commit.

## Verification

- `pnpm --dir auth test:integration`: 15 files, 116 tests passed against an
  isolated real PostgreSQL instance.
- `pnpm test`: 866 Python tests, 155 Auth tests, and 107 Web tests passed.
- `pnpm test:e2e`: 16/16 real-browser tests passed through Caddy.
- `pnpm test:caddy-image-smoke`: passed against the production Web image.
- Standards review: PASS after closing cross-instance credential-lock ordering,
  exact Session/Reset compensation, and fail-closed causal cancellation when
  compensation itself fails.
- Spec review: PASS after rechecking exact Proof binding, atomic Invitation
  replacement, ordinary-Researcher `404`, password handling, and the agreed
  singleton-Operator scope.
