# Hosted health operations

Hosted V2 has three private Grafana views. They are operator evidence, not a
User API, and Grafana is not published through the public Origin.

Grafana binds only to host loopback on port `3001`. On the node, open
`http://127.0.0.1:3001`; remotely, create an SSH tunnel and then use the same
local URL:

```sh
ssh -L 3001:127.0.0.1:3001 operator@host
```

Authenticate with `GRAFANA_ADMIN_USER` and the separately stored
`GRAFANA_ADMIN_PASSWORD`. Do not bind this port to a public interface or add a
Caddy route.

## Daily inspection

At least once per calendar day, the Operator records that all three dashboards
were inspected:

1. **System Health** — check public dependencies, API/ObjectStore/Temporal
   readiness, the three outbox queues, four-slot Workflow capacity, Worker
   heartbeat age, persistent-disk pressure, and Collector export failures.
2. **Data Health** — check Tushare reachability, current Dataset Release age,
   manifest validation, coverage, schema and lineage evidence, recent failed
   Dataset Publications, and preservation of the previous authoritative
   Release.
3. **Quantitative Semantic Health** — check the pinned deterministic fixture
   regression, numeric and accounting invariants, checksum and missingness
   evidence, and the latest explicit Batch-Incremental Equivalence result. This
   view never treats Alpha return, Sharpe, or profitability as health.

V1 deliberately has no alert-delivery service. The accepted detection delay is
therefore up to 24 hours. A red check is investigated in its own plane before
any decision to close the public Origin.

## Probe boundaries

Application services expose `/live` and `/ready` on private container ports.
Compute Workers, the Data Worker, relay, and Tushare egress use port `9100`;
the Health service uses `8020`; ObjectStore uses `8010`; API uses `8000`.

- Liveness proves only that the process can answer a cheap in-memory request.
- Readiness proves that the role completed its startup dependency handshake.
- Neither probe writes Storage, publishes a Dataset, starts a Workflow, calls
  Tushare, or runs the quantitative regression.
- Tushare loss degrades Data Health but does not change API, Compute, or relay
  readiness. Collector loss degrades `telemetry`; an external trace backlog
  degrades `trace_export`. Neither blocks product work.

The Health service runs the deterministic quantitative regression once in a
background thread after startup. Until it completes, the Quantitative Semantic
Health view remains degraded rather than blocking service readiness.

`release_freshness` requires both a successful publication whose requested
session matches the authoritative Release and a bounded Release age. The
default bound is 345,600 seconds (four days), which covers an ordinary weekend
without allowing a stopped publication schedule to remain green forever. Set
`THESISTRACE_RELEASE_FRESHNESS_MAX_SECONDS` to an explicitly reviewed local
market-calendar bound when operating across a longer exchange holiday.

In production, the System Health Public-Origin probe uses
`THESISTRACE_SITE_ADDRESS` and validates its public certificate through the
Cloudflare hostname. Only the localhost launcher substitutes
`host.docker.internal`, preserves `Host/SNI=localhost`, and disables
certificate verification for the generated local Caddy certificate.

## Retention and privacy

- Prometheus is capped by both `--storage.tsdb.retention.time=7d` and
  `--storage.tsdb.retention.size=5GB`.
- Docker's `json-file` driver retains at most five 20-MB files per container.
- Collector tail sampling retains failed Task traces at 100%, successful Task
  traces at 10%, and ordinary successful HTTP traces at 1%.
- The configured external OTLP backend must enforce a seven-day trace
  retention policy. ThesisTrace keeps no local trace index.
- The Collector queue is bounded at 2,048 batches. External-export backlog,
  export failures, and queue drops are visible through the queue-utilization,
  `otelcol_exporter_send_failed_spans`, and
  `otelcol_exporter_enqueue_failed_spans` series on System Health. Export retry is
  non-blocking and never propagates into a product request.
- Metric labels are fixed service, slot, view, check, and measurement names.
  Logs are bounded JSON and redact credentials, email addresses, Personal
  Workspace IDs, and Alpha field expressions. Spans contain only fixed
  operation classes, HTTP method/status, service name/version, and exception
  type; they never contain request bodies, URLs, resource IDs, market data, or
  result payloads.

## Plane-isolated fault practice

Use the following only during a maintenance window. Set exactly one value in
`.hosted/hosted.env`, recreate the private Health service, inspect all three
views, then remove the value and recreate it again:

```text
THESISTRACE_HEALTH_FAULT_PLANE=system
THESISTRACE_HEALTH_FAULT_PLANE=data
THESISTRACE_HEALTH_FAULT_PLANE=quantitative
```

Run:

```sh
docker compose --project-name thesistrace-hosted \
  --project-directory . \
  --env-file .hosted/hosted.env \
  --file deploy/hosted/compose.yaml \
  up --detach --force-recreate health-service
```

The maintenance hook changes one real evidence input: System forces API
dependency evidence down, Data forces Tushare reachability down, and
Quantitative forces the deterministic-regression evidence down. Health service
readiness and the other two dashboards remain unchanged.

## Configuration validation

Before a release, validate the bounded observability configuration with the
pinned images:

```sh
docker run --rm \
  -e THESISTRACE_EXTERNAL_OTLP_ENDPOINT=http://127.0.0.1:4319 \
  -e THESISTRACE_EXTERNAL_OTLP_INSECURE=true \
  -v "$PWD/deploy/hosted/otel-collector.yaml:/etc/otelcol-contrib/config.yaml:ro" \
  otel/opentelemetry-collector-contrib:0.136.0 \
  validate --config=/etc/otelcol-contrib/config.yaml

docker run --rm --entrypoint promtool \
  -v "$PWD/deploy/hosted/prometheus.yaml:/etc/prometheus/prometheus.yml:ro" \
  prom/prometheus:v3.6.0 \
  check config /etc/prometheus/prometheus.yml
```
