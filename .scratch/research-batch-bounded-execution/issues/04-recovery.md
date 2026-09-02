# Recover only complete Alpha and Strategy units

**Status:** complete

Create durable task Attempts when the corresponding start event is accepted, use
an explicit transient allowlist, and make resource exhaustion terminal for the
unchanged execution plan.

## Acceptance

- Pre-start and mid-unit crashes cannot create a fenced restart loop.
- An incomplete whole unit has at most three transient Attempts.
- Completed Results/private artifacts survive retry; ephemeral scratch does not.

## Comments

- 2026-09-03: Implemented start-transaction Attempt creation, the explicit
  transient allowlist, three-Attempt ceiling, terminal resource exhaustion, and
  complete-unit restart in `141594d`. PostgreSQL and RustFS Factor/Strategy
  restart gates, crash injection, and the full release gate passed at `d2adced`.
