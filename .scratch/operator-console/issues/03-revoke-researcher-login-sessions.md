# 03 — Revoke another Researcher's Login Sessions

**What to build:** Let the Operator remove every active Login Session belonging
to another Researcher after an exact password-confirmed decision, without
allowing the only Operator to revoke the current Operator's own Sessions.

**Blocked by:** 02 — Secure Invitation mutations with Operator Proof.

**Status:** ready-for-agent

- [ ] A Researcher row exposes its current Login Session count and offers
  revocation only when the target is not the current Operator.
- [ ] The confirmation dialog identifies the target Researcher, shows the current
  Session count and effect, and requires a proof bound to that exact target.
- [ ] Successful revocation invalidates every existing Login Session belonging to
  the target Researcher and immediately refreshes the displayed count.
- [ ] The current Operator cannot target itself through the UI, direct API, stale
  page state, or a modified request; rejection has no Session side effect.
- [ ] Invalid, expired, mismatched, concurrently consumed, or replayed proof has
  no Session side effect.
- [ ] The target Researcher's next authenticated request is rejected while the
  acting Operator remains signed in.
- [ ] Auth integration tests use real PostgreSQL and real Session records to prove
  successful revocation, race behavior, self-protection, and ordinary-Researcher
  `404` behavior.
- [ ] A real browser test proves the confirmation copy, successful revocation,
  visible count update, target logout, and preserved Operator Session.
