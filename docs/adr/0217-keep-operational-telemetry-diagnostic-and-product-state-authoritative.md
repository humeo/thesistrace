# Keep operational telemetry diagnostic and Product State authoritative

PostgreSQL Product State alone decides ownership, leases, retries, recovery, cancellation, Stop, and publication. Logs, health responses, and diagnostic snapshots are disposable explanations that may be lost or rotated and are never replayed into state.
