# 02 — Secure Invitation mutations with Operator Proof

**What to build:** Let the Operator issue and reissue Researcher Invitations from
the Console only after confirming the current password, with each authorized
mutation bound to one exact request and unusable afterward.

**Blocked by:** 01 — Establish the singleton Operator and read-only Console.

**Status:** ready-for-agent

- [ ] Every Invitation mutation opens an accessible confirmation dialog showing
  the action, target email, and effect before requesting the current password.
- [ ] Successful password confirmation produces an Operator Proof valid for 60
  seconds and one successful consumption, bound to the current Login Session,
  operation name, and canonical exact request content.
- [ ] Issuing an Invitation uses the existing canonical-email, admission,
  delivery, expiry, and invite-only account rules and refreshes the visible
  Invitation state after success.
- [ ] Reissuing an Invitation clearly warns that the old link will become invalid
  and atomically leaves exactly one effective Invitation when delivery succeeds.
- [ ] Failed validation, delivery failure, invalid password, proof expiry,
  request mismatch, Session mismatch, concurrent duplicate consumption, and
  replay produce no unauthorized mutation and preserve the prior effective
  Invitation.
- [ ] The browser never persists or forwards the current password beyond the Auth
  confirmation request, and the password is cleared when the dialog closes or
  completes.
- [ ] Ordinary Researchers receive `404` from proof and Invitation mutation APIs.
- [ ] Auth unit and isolated real-PostgreSQL integration tests cover exact proof
  binding, expiry, single consumption, concurrency, replay, issue, reissue, and
  delivery failure without implementation-detail assertions.
- [ ] A real browser test through Caddy proves issue, reissue, old-link
  invalidation, keyboard operation, Escape behavior, and focus restoration.
