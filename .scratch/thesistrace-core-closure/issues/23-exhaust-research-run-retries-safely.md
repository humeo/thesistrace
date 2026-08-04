# 23 — Exhaust ResearchRun retries safely

**What to build:** Keep transient infrastructure retries inside one
ResearchRun and produce one readable terminal failure when its bounded retry
policy is exhausted.

**Blocked by:** 22.

**Status:** ready-for-agent

**Implementation:** complete

- [x] Eligible transient failures retry the same ResearchRun instead of
  creating a user-visible Run or Rerun.
- [x] While automatic retry remains possible, the product state remains
  `running`.
- [x] Exhaustion commits exactly one `failed` terminal state with a sanitized,
  readable reason.
- [x] Succeeded, failed, and cancelled terminal states cannot be overwritten by
  a later Attempt.
- [x] Retry state survives worker restart but remains internal.
- [x] Retry is bounded; a permanently failing Run cannot loop forever.

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

- ResearchRuns now derives durable retry eligibility from its PostgreSQL
  Attempt history. A general transient infrastructure failure permits at most
  three total Attempts; resource exhaustion permits at most two total Attempts
  for the whole Run, even when the later failure changes type or the worker is
  lost. No retry creates another ResearchRun or user-visible Rerun.
- Publication distinguishes `PublicationUnavailableError` from deterministic
  preparation and verification failures. S3 5xx, explicit temporary service
  codes, and concrete botocore connection/timeout failures are retryable; 403,
  invalid payload/identifier/contract, missing or conflicting content, checksum
  failures, and permission errors terminate immediately. PostgreSQL operational
  connection failures and explicit Python connection/timeouts remain eligible.
- While another Attempt is eligible, the Run remains publicly `running` and
  exposes no retry state. Exhaustion or a permanent failure commits one
  `failed` state with one fixed readable `failure_reason`; exception messages,
  Attempt reasons, counts, leases, and fences remain private. The Web renders
  only that sanitized terminal reason.
- Acceptance pauses a real worker after Publication preparation, commits a
  newer succeeded, failed, or cancelled fence, then releases the stale worker.
  The late success/failure paths cannot overwrite the terminal state or add a
  Result manifest. Restart recovery and mixed resource/infrastructure/worker
  loss sequences use the same persisted Run identity and Attempt history.
- The final ticket backend command written above passed `27 passed, 1 warning`
  in `45.74s` against real PostgreSQL and RustFS. The final Core browser command
  passed `8 passed` in `33.4s`; the command's final `down` removed the isolated
  containers.
- Independent review initially found that the resource limit was scoped only
  to the current error type, deterministic Publication/OSError failures were
  classified too broadly as transient, and the terminal test did not hold a
  real stale Attempt. Commit `7f00dd1` added Run-history limits, a narrow
  Publication unavailable type, mixed-failure coverage, and real stale-worker
  fences. Final review passed `Standards: PASS` and `Spec: PASS` with no
  findings.
- The final repository `make check` invocation exited `0`: Ruff passed, Python
  passed `521 passed, 81 skipped, 2 warnings` in `607.17s`, Web typecheck and
  production build passed, and narrow/desktop Playwright passed in `32.9s` and
  `34.2s`.
