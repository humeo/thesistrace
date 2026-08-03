# 41 — Remove Hosted operations and observability runtime

**What to build:** Delete inactive Hosted operations, capacity, and launch
machinery so operational scope cannot block or leak into the Core product.

**Blocked by:** 40.

**Status:** ready-for-agent

- [ ] The Hosted archive ref is reverified before deletion.
- [ ] Quota profiles, hosted admission policy, disk-pressure modes, maintenance,
  backup, restore, rollback, and launch-qualification runtime code are removed.
- [ ] Hosted health dashboards, alerting, release evidence, and operator
  telemetry services are removed with their callers, targets, dependencies, and
  tests.
- [ ] Core product states and sanitized failure reasons remain available without
  an Operations Ledger or System Health product.
- [ ] Historical operations ADRs and research remain recoverable but are marked
  clearly outside the active Core.
- [ ] The default Core gate requires no capacity or production-launch evidence.

**How to verify:**

- Run `uv run pytest -q tests/architecture tests/integration tests/acceptance`
  with no hosted health, telemetry, backup, or operator process available.
- Inspect active commands and dependencies; no Core startup or check may invoke
  removed operations or qualification machinery.

## Comments
