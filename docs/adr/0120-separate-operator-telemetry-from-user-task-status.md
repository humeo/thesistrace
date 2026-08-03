---
status: superseded by ADR-0151
---

# Separate operator telemetry from user task status

Hosted Platform V2 exposes raw platform logs, metrics, traces, and health evidence only to operators, while a User sees only authorized product state and sanitized failures for resources in their Personal Workspace. This separation prevents cross-Personal Workspace leakage and avoids making the operational telemetry system a User-facing authorization surface.
