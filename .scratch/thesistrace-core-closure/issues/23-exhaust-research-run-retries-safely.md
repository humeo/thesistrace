# 23 — Exhaust ResearchRun retries safely

**What to build:** Keep transient infrastructure retries inside one
ResearchRun and produce one readable terminal failure when its bounded retry
policy is exhausted.

**Blocked by:** 22.

**Status:** ready-for-agent

- [ ] Eligible transient failures retry the same ResearchRun instead of
  creating a user-visible Run or Rerun.
- [ ] While automatic retry remains possible, the product state remains
  `running`.
- [ ] Exhaustion commits exactly one `failed` terminal state with a sanitized,
  readable reason.
- [ ] Succeeded, failed, and cancelled terminal states cannot be overwritten by
  a later Attempt.
- [ ] Retry state survives worker restart but remains internal.
- [ ] Retry is bounded; a permanently failing Run cannot loop forever.

**How to verify:**

- Run `uv run pytest -q tests/integration tests/acceptance` with recoverable and
  permanent infrastructure failures across process restart.
- Confirm the public lifecycle stays on one Run ID, shows running during retry,
  and ends once with the expected sanitized failure.

## Comments
