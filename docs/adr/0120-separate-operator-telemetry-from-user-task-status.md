---
status: accepted
---

# Separate operator telemetry from user task status

Observability in the first hosted release is an operator capability. Operators
may inspect platform-wide logs, metrics, dashboard states, and the correlation
data needed to follow work across the control, scheduling, data, and compute
planes. That capability covers System Health, Data Health, and Quantitative
Semantic Health; infrastructure utilization alone is not sufficient.

An authenticated User sees only the product state of resources in their
Personal Workspace: task status, progress, timestamps, and a sanitized failure
reason with a stable error code. Dataset Publication status is
platform-operational state and is not exposed as tenant-owned task telemetry.

Raw logs, system metrics, traces, stack traces, host details, and service-level
diagnostics are not exposed through the tenant product interface in the first
hosted release. This prevents cross-Workspace information leakage and avoids
turning the operational telemetry system into a tenant-facing authorization and
retention surface.
