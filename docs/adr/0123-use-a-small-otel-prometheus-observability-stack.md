---
status: superseded by ADR-0151
---

# Use a small OpenTelemetry and Prometheus observability stack

The first hosted deployment uses OpenTelemetry instrumentation and Collector, Prometheus, Grafana, bounded structured JSON logs, and non-blocking export to an external trace backend, without local trace or log indexing services. This small, sanitized, bounded stack covers System Health, Data Health, and Quantitative Semantic Health without exhausting the single node or exposing Personal Workspace data.
