# 03 — Revoke another Researcher's Login Sessions

**What to build:** Let the Operator remove every active Login Session belonging
to another Researcher after an exact password-confirmed decision, without
allowing the only Operator to revoke the current Operator's own Sessions.

**Blocked by:** 02 — Secure Invitation mutations with Operator Proof.

**Status:** complete

- [x] A Researcher row exposes its current Login Session count and offers
  revocation only when the target is not the current Operator.
- [x] The confirmation dialog identifies the target Researcher, shows the current
  Session count and effect, and requires a proof bound to that exact target.
- [x] Successful revocation invalidates every existing Login Session belonging to
  the target Researcher and immediately refreshes the displayed count.
- [x] The current Operator cannot target itself through the UI, direct API, stale
  page state, or a modified request; rejection has no Session side effect.
- [x] Invalid, expired, mismatched, concurrently consumed, or replayed proof has
  no Session side effect.
- [x] The target Researcher's next authenticated request is rejected while the
  acting Operator remains signed in.
- [x] Auth integration tests use real PostgreSQL and real Session records to prove
  successful revocation, race behavior, self-protection, and ordinary-Researcher
  `404` behavior.
- [x] A real browser test proves the confirmation copy, successful revocation,
  visible count update, target logout, and preserved Operator Session.

## Implementation Plan

1. **Bind one Proof to one immutable Researcher target.** Extend the existing
   60-second Operator Proof contract with `researcher.sessions.revoke`, hashing
   the operation and exact Researcher UUID rather than an editable label or
   email. Keep Invitation Proof requests as their existing strict union branch;
   reject mixed, extra, malformed, expired, mismatched, replayed, or
   cross-Session requests without a compatibility path.
2. **Serialize revocation with credential creation.** Route both private CLI and
   Console Session revocation through the existing canonical-email credential
   coordinator. A sign-in already in flight finishes before revocation deletes
   its Session; a later sign-in starts only after revocation completes. The
   mutation removes every Session row for the target while leaving the
   Researcher active and all other access state unchanged.
3. **Consume Proof and protect the singleton atomically.** Add a focused
   Operator Session service that claims the Proof before mutation, then in one
   transaction rechecks the current Operator Assignment and acting Login
   Session, rejects the current Operator as a target, consumes the exact Proof,
   deletes the target Sessions, records the existing internal security event,
   and commits. Transfer, stale-page, duplicate, and concurrent paths fail
   closed with no Session side effect.
4. **Expose one same-origin Operator mutation.** Add a strict Auth endpoint for
   the exact Researcher UUID and opaque Proof. Ordinary Researchers receive an
   empty `404`; invalid proof, protected target, stale target, origin failure,
   and service failure remain sanitized and never receive or forward the
   password.
5. **Add the accessible row action and confirmation.** Show the current Session
   count with a Revoke Sessions action only for another Researcher with active
   Sessions. The modal identifies the Researcher, count, and logout effect,
   requires the current password, traps keyboard focus, supports Escape, clears
   the password, reloads the directory after success, and restores focus to the
   trigger or the existing page fallback.
6. **Prove the boundary at real seams.** Add unit/HTTP tests plus isolated real
   PostgreSQL tests for success, self-protection, target and Session mismatch,
   replay, concurrent proof consumption, Operator transfer, and an overlapping
   sign-in. Extend the real Caddy browser flow to prove copy, count refresh,
   target logout, Operator preservation, password non-forwarding, and ordinary
   `404`, then run host, Auth integration, E2E, Production Caddy, and both review
   gates before the ticket's independent commit.

## Verification

- `pnpm --dir auth test:integration`: 16 files, 123 tests passed against an
  isolated real PostgreSQL instance, including a PostgreSQL-gated real HTTP
  sign-in overlapping Session revocation.
- `pnpm test`: Ruff passed; 866 Python tests, 160 Auth tests, and 109 Web tests
  passed, with Auth and Web typechecks passing.
- `pnpm test:e2e`: 16/16 real-browser tests passed through Caddy after the final
  review fixes, including Escape and Cancel focus restoration.
- `pnpm test:caddy-image-smoke`: passed against the production Web image.
- Standards review: PASS after replacing the synthetic Session INSERT race with
  the real HTTP sign-in boundary and adding the Cancel focus regression.
- Spec review: PASS after verifying exact target Proof binding, singleton
  self-protection, target logout, preserved Operator access, password isolation,
  and ordinary-Researcher empty `404` behavior.
