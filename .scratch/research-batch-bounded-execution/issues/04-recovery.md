# Recover only complete Alpha and Strategy units

**Status:** ready-for-agent

Create durable task Attempts when the corresponding start event is accepted, use
an explicit transient allowlist, and make resource exhaustion terminal for the
unchanged execution plan.

## Acceptance

- Pre-start and mid-unit crashes cannot create a fenced restart loop.
- An incomplete whole unit has at most three transient Attempts.
- Completed Results/private artifacts survive retry; ephemeral scratch does not.

## Comments
