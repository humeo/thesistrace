# Private Data Operator

The Data Operator is a deployment-private command. It is not an HTTP route or
a Web capability, and normal API/Worker startup never runs it.

Bootstrap is explicit and only establishes the first Head of an empty mounted
Canonical Data Store. Freeze a timezone-aware operator instant and supply an
idempotency key:

```sh
docker compose -f deploy/core/compose.yaml run --rm \
  -e THESISTRACE_TUSHARE_TOKEN \
  api thesistrace-data-operator-v1 bootstrap \
  --idempotency-key bootstrap-2026-08-09 \
  --as-of 2026-08-09T18:00:00+08:00
```

The default collection window begins one natural year before the Shanghai
calendar date at `--as-of`. Calendar collection stops at the frozen completion
cutoff; market facts stop at the latest Research Session jointly open on SSE
and SZSE. This window is an operator convenience, not a Research Period,
Warm-up, or minimum-session rule.

For deterministic development or incident reproduction, pass a bounded
version-1 Tushare replay instead of a token:

```sh
thesistrace-data-operator-v1 bootstrap \
  --idempotency-key bootstrap-replay-1 \
  --as-of 2026-08-09T18:00:00+08:00 \
  --replay /private/operator/tushare-bootstrap-replay.json
```

Bootstrap records internal preparation time in the Head but does not set a
successful Refresh timestamp. Repeating the same key and request returns the
same outcome. A different key cannot overwrite an existing Head.

The narrow Production Image smoke builds the backend image, runs the versioned
operator twice through the shared named mount, and then starts and restarts the
API and Worker without source credentials:

```sh
./scripts/smoke-data-operator-image
```
