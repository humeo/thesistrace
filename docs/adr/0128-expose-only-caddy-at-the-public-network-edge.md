---
status: superseded by ADR-0143
---

# Expose only Caddy at the public network edge

Hosted Platform V2 runs Caddy as the single public reverse proxy on the first
Compose node. Caddy is the only application container that binds public host
ports, accepting HTTP and HTTPS on ports 80 and 443, redirecting HTTP to HTTPS,
terminating TLS, serving the production Web build, and forwarding authorized
end-user routes to the ThesisTrace API and the required InsForge Auth and
Storage endpoints.

PostgreSQL, Temporal Service, Temporal UI, InsForge administration,
Prometheus, Grafana, OpenTelemetry Collector, Data Workers, and Compute Workers
remain on private Docker networks and publish no public host ports. Operator
access to private dashboards uses an SSH tunnel in the first hosted release.
Caddy's administration endpoint is not exposed publicly.

Application services trust forwarded client and scheme information only from
Caddy. Direct container addresses are not product API surfaces, and internal
health, metrics, Workflow, database, and worker endpoints remain unavailable to
Users. Exporting sampled traces to an external backend uses outbound traffic
and does not create another inbound public service.

The first hosted release uses one public hostname and one browser Origin.
Caddy serves the Web at the root, forwards the versioned ThesisTrace API
prefix, and forwards only the InsForge Auth and Storage routes required by the
product. This avoids a separate backend hostname and cross-origin browser
configuration. Exact InsForge path prefixes must be verified against the pinned
InsForge release during implementation rather than being invented in this
architecture decision; administrative routes remain private regardless of
their prefix.
