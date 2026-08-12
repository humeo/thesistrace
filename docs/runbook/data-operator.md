# Private Data Operator

The Data Operator is a deployment-private command. It is not an HTTP route or
a Web capability, and normal API/Worker startup never runs it.

Bootstrap is explicit and only establishes the first Head of an empty mounted
Canonical Data Store. Freeze a timezone-aware operator instant and supply an
idempotency key:

```sh
docker compose -f deploy/core/compose.yaml run --rm \
  -e THESISTRACE_TUSHARE_TOKEN \
  api thesistrace-data-operator bootstrap \
  --idempotency-key bootstrap-2026-08-09 \
  --start-date 2026-07-09 \
  --as-of 2026-08-09T18:00:00+08:00
```

Use `--start-date YYYY-MM-DD` to bound the initial collection window. If it is
omitted, the window begins one natural year before the Shanghai calendar date
at `--as-of`. The start date must not be later than the completed market day.
Calendar collection stops at the frozen completion cutoff derived from
`--as-of`; market facts stop at the latest Research Session jointly open on SSE
and SZSE. This window is an operator convenience, not a Research Period,
Warm-up, or minimum-session rule.

For deterministic development or incident reproduction, pass a bounded
version-2 Tushare replay instead of a token:

```sh
thesistrace-data-operator bootstrap \
  --idempotency-key bootstrap-replay-1 \
  --as-of 2026-08-09T18:00:00+08:00 \
  --replay /private/operator/tushare-bootstrap-replay.json
```

Bootstrap records internal preparation time in the Head but does not set a
successful Refresh timestamp. Repeating the same key and request returns the
same outcome. A different key cannot overwrite an existing Head.

Live bootstrap persists a bounded, token-free foundation checkpoint containing
the calendars and instrument reference before starting market-fact collection.
If a later provider call fails, rerun the same request window with a new
idempotency key; the operator reports `bootstrap_checkpoint/restored` and
resumes at market facts. Changing the request window does not reuse the
checkpoint. Successful publication clears it.

## Refresh and collection

Refresh is a private two-step operation. Submission records the frozen request;
work execution later claims the next request and collects from Tushare:

```sh
docker compose -f deploy/core/compose.yaml run --rm api \
  thesistrace-data-operator refresh \
  --idempotency-key refresh-2026-08-12 \
  --as-of 2026-08-12T18:00:00+08:00

docker compose -f deploy/core/compose.yaml run --rm \
  -e THESISTRACE_TUSHARE_TOKEN \
  api thesistrace-data-operator work-refresh
```

Use `work-refresh --replay /private/operator/replay.json` for deterministic
reproduction. Inspect an operation without changing it:

```sh
thesistrace-data-operator inspect-refresh \
  --idempotency-key refresh-2026-08-12
```

Garbage collection is explicit and idempotent:

```sh
thesistrace-data-operator collect \
  --idempotency-key collect-2026-08-12
```

Collection retains the current Head, live candidates, and active execution
pins. It does not make completed ResearchRuns depend on permanently retained
market-data Generations.

The narrow Production Image smoke builds the backend image, runs the versioned
operator twice through the shared named mount, and then starts and restarts the
API and Worker without source credentials:

```sh
./scripts/smoke-data-operator-image
```
