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

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/integration \
  tests/acceptance/test_core_research_run_retry.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:core
./scripts/core-test-runtime down
```

The tests must use real PostgreSQL and RustFS to inject an eligible transient
infrastructure failure that later succeeds across a fresh runtime, a permanent
failure, deterministic Publication/permission errors, and repeated transient
failure through exhaustion. Mixed sequences must prove that any earlier
resource exhaustion keeps the whole Run at the two-Attempt limit even when the
second failure is infrastructure loss or worker loss. The tests must also prove
that every Attempt stays under one ResearchRun identity, the public state stays
`running` while another automatic retry is eligible, exhaustion publishes no
Result and commits one terminal `failed` state with a readable sanitized
reason, a real stale Attempt cannot overwrite succeeded, failed, or cancelled,
and persisted retry state cannot loop past its configured bound or enter the
product projection. The browser must render the terminal sanitized reason on
the ResearchRun detail and must not expose Attempt, retry count, exception
text, or other execution mechanics.

## Comments
