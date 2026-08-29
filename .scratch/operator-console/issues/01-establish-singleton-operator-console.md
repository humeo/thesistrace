# 01 — Establish the singleton Operator and read-only Console

**What to build:** Give the one Researcher holding the Operator Capability a
discoverable, read-only Operator Console for reviewing Researchers and
Invitations, while keeping the entire surface undiscoverable to every ordinary
Researcher.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] A deployment-private command assigns the Operator Capability only to an
  existing active Researcher, and attempting to establish a second Operator is
  rejected without changing the current Operator Assignment.
- [ ] A deployment-private transfer atomically assigns the new Operator and
  revokes every Login Session of the former Operator; there is never a visible
  intermediate state with zero or two Operators.
- [ ] The Operator sees an Operator navigation entry at the bottom of the
  existing sidebar and can open `/operator/researchers` in the normal application
  shell.
- [ ] An ordinary Researcher sees no Operator navigation and receives `404` from
  direct Operator page and read-API requests.
- [ ] The Researcher view shows display label, canonical email, Researcher ID,
  active state, creation time, latest successful login, current Login Session
  count, effective Invitation, and terminal Invitations in the existing 30-day
  window.
- [ ] Researcher and Invitation results use stable server-side 50-row pagination;
  Researcher search accepts canonical email or display label.
- [ ] The read APIs and browser view expose no IP address, User-Agent, full
  security history, export function, or mutation that is out of scope.
- [ ] Auth unit and isolated real-PostgreSQL integration tests prove singleton
  assignment, transfer, Session revocation, projections, search, pagination, and
  fail-closed ordinary-Researcher access.
- [ ] A real browser test proves the Operator and ordinary Researcher navigation
  and direct-route behavior through the same-origin application.
