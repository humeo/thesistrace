# 01 — Establish the singleton Operator and read-only Console

**What to build:** Give the one Researcher holding the Operator Capability a
discoverable, read-only Operator Console for reviewing Researchers and
Invitations, while keeping the entire surface undiscoverable to every ordinary
Researcher.

**Blocked by:** None — can start immediately.

**Status:** complete

- [x] A deployment-private command assigns the Operator Capability only to an
  existing active Researcher, and attempting to establish a second Operator is
  rejected without changing the current Operator Assignment.
- [x] A deployment-private transfer atomically assigns the new Operator and
  revokes every Login Session of the former Operator; there is never a visible
  intermediate state with zero or two Operators.
- [x] The Operator sees an Operator navigation entry at the bottom of the
  existing sidebar and can open `/operator/researchers` in the normal application
  shell.
- [x] An ordinary Researcher sees no Operator navigation and receives `404` from
  direct Operator page and read-API requests.
- [x] The Researcher view shows display label, canonical email, Researcher ID,
  active state, creation time, latest successful login, current Login Session
  count, effective Invitation, and terminal Invitations in the existing 30-day
  window.
- [x] Researcher and Invitation results use stable server-side 50-row pagination;
  Researcher search accepts canonical email or display label.
- [x] The read APIs and browser view expose no IP address, User-Agent, full
  security history, export function, or mutation that is out of scope.
- [x] Auth unit and isolated real-PostgreSQL integration tests prove singleton
  assignment, transfer, Session revocation, projections, search, pagination, and
  fail-closed ordinary-Researcher access.
- [x] A real browser test proves the Operator and ordinary Researcher navigation
  and direct-route behavior through the same-origin application.

## Implementation Plan

1. **Make Operator Assignment a hard Auth schema contract.** Add one
   `auth.operator_assignment` singleton row that references an existing
   Researcher, grant only `auth_runtime` access, and update the exact PostgreSQL
   catalog fingerprint. The snapshot is installed only into an absent or empty
   Auth scope; a populated old scope fails verification and is never migrated.
2. **Implement the private assignment lifecycle first.** Add one Auth-owned
   service and deployment-private `assign-operator` / `transfer-operator`
   commands accepting exactly one of `--email` or `--researcher-id`.
   Establishment serializes concurrent callers, requires an active Researcher,
   and rejects any second assignment unchanged. Transfer replaces the singleton
   row and deletes every Login Session of the former Operator in one transaction;
   existing deactivation machinery may not leave the assigned Operator inactive.
3. **Expose a fail-closed read boundary owned entirely by Auth.** Add an internal
   page-access check for Caddy plus public same-origin read-only endpoints at
   `/api/auth/operator/capability`, `/api/auth/operator/researchers`, and
   `/api/auth/operator/invitations`. Every request resolves the current active
   Login Session against the current Operator Assignment; anonymous, inactive,
   malformed, or ordinary-Researcher requests return `404`, while dependency
   failure returns the existing sanitized `503` contract.
4. **Build bounded projections, not an administration backend.** Researcher
   results are ordered by creation time then ID, descending, searched by
   canonical-email/display-label substring, and returned in fixed 50-row pages.
   Invitation results use the same stable reverse-chronological 50-row paging.
   Opaque authenticated cursors are bound to their collection, order, and
   normalized search. The Researcher rows expose only the ticket fields and the
   effective unexpired Invitation; the separate Invitation table exposes
   effective records plus terminal records inside the existing 30-day window,
   allowing the page to show terminal history without an unbounded nested row.
5. **Gate the real same-origin page as well as its data.** Route `/operator` and
   `/operator/*` through Caddy `forward_auth` to the internal Auth check before
   serving the SPA, so an ordinary direct document request receives HTTP `404`.
   After Session verification the browser fetches the Auth-derived capability,
   preserves Auth-unavailable fail-closed behavior, shows the bottom-of-sidebar
   Operator entry only when granted, and renders `/operator/researchers` inside
   the existing shell. The page uses the repository's dense dark table patterns,
   explicit loading/empty/error states, responsive labeled rows, and no mutation,
   export, client metadata, security-history, IP-address, or User-Agent surface.
6. **Drive each seam red-green and qualify the whole ticket.** Start with Auth
   unit tests for command parsing, access decisions, cursor validation, and
   response shaping; then isolated real-PostgreSQL tests for concurrency,
   singleton preservation, atomic transfer, Session revocation, search,
   projection timing, and pagination. Add Web shell/component tests and one real
   Playwright flow through Caddy covering Operator and ordinary navigation,
   direct-document `404`, read-API `404`, paging, and visible fields. Run affected
   host, integration, E2E, and Caddy image gates, perform the required two-axis
   code review, fix and re-review every finding, then check this ticket, mark it
   `complete`, and create its independent commit before opening Ticket 02.

## Verification

- `pnpm test`: 866 Python, 150 Auth, and 105 Web tests passed; Auth and Web
  typechecks passed.
- `pnpm --dir auth test:integration`: 97 isolated real-PostgreSQL integration
  tests passed.
- `pnpm test:e2e`: 16 real-browser tests passed, including singleton Operator
  access, ordinary-Researcher empty `404`, visible directory fields, 55-row
  paging, and loading-time control locking.
- `pnpm test:caddy-image-smoke`: Production Caddy image gate passed, including
  the Operator document authorization boundary.
- Standards re-review: PASS. Spec re-review: PASS. Every first-review finding
  was fixed before completion.
