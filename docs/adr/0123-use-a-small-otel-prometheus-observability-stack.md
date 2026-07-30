---
status: accepted
---

# Use a small OpenTelemetry and Prometheus observability stack

The first hosted deployment uses the following minimum operational
observability stack on its single Compose node:

- OpenTelemetry SDK instrumentation in the application processes;
- one OpenTelemetry Collector for receiving, processing, sampling, and
  exporting telemetry;
- Prometheus for local metrics storage;
- Grafana for operator dashboards and visible warning states; and
- structured JSON application logs written to container stdout and stderr,
  with bounded rotation configured through the Docker logging driver.

The metrics and logs cover System Health, Data Health, and Quantitative
Semantic Health. They do not replace stage-specific tests or regression
evidence. Prometheus retains at most seven days or 5 GiB of local time-series
data, whichever limit is reached first.

The node does not run a local Trace storage backend such as Tempo in the first
hosted release. The Collector exports retained traces over OTLP to an external
low-cost observability service. Trace export is non-blocking for product work;
the Collector uses bounded resources, and export backlog or dropped telemetry
raises an operator-visible signal.

Task-attempt traces are eligible for tail-based sampling because their final
outcome is not known when they start. Failed task traces are retained at 100%;
successful task traces are sampled at 10%, and ordinary successful HTTP traces
are sampled at 1%. The external trace backend retains exported traces for seven
days.

Logs and traces must not contain passwords, tokens, raw credentials, email
addresses, Alpha Expressions, raw market-data payloads, or immutable result
payloads. They use opaque correlation identifiers and sanitized error details.
Metrics do not use User, Workspace, task, Attempt, or trace identifiers as
labels.

The first hosted release adds no local log-indexing service. Operators inspect
rotated container JSON logs directly unless the external observability service
is separately configured to ingest them. Docker rotates each container's JSON
log at 20 MB and keeps five files, limiting one container to approximately
100 MB of local logs. Prometheus data and rotated container logs together stay
within an approximately 7-GiB local observability budget; the node still runs
no Loki, Tempo, or Elasticsearch service.
