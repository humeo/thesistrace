---
status: superseded by ADR-0151
scope: archived - outside the active Core
---

# Separate liveness, readiness, and System Health

Hosted Platform V2 distinguishes cheap process liveness, role-specific readiness, and aggregate System Health instead of treating every dependency failure as whole-product failure. This separation blocks only work whose dependencies are unavailable and avoids using expensive or mutating checks as health probes.
