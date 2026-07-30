---
status: accepted
---

# Route public HTTP through Cloudflare before Caddy

Hosted Platform V2 keeps one public browser Origin, but its HTTP and HTTPS DNS
record is Cloudflare-proxied rather than DNS-only. Cloudflare is the external
public edge. Caddy remains the only application container that binds host ports
80 and 443 on the Compose node; it terminates the origin-side HTTPS connection,
serves the production Web build, and forwards only the required ThesisTrace
API, InsForge Auth, and InsForge Storage routes.

The host firewall or cloud security group accepts origin traffic on ports 80
and 443 only from Cloudflare's published proxy address ranges. Direct public
access to the origin is rejected, and no other application or administration
port is exposed. PostgreSQL, Temporal Service, Temporal UI, InsForge
administration, Prometheus, Grafana, OpenTelemetry Collector, Data Workers, and
Compute Workers remain on private Docker networks. Operator SSH access remains
separate from the public application path.

Cloudflare applies explicit coarse client-IP rate limits to the public
email-and-password registration, login, verification, and password-recovery
routes. Merely enabling the proxy is not treated as configuring those rules.
Exact thresholds are deployment configuration validated with security and
traffic evidence. Cloudflare-managed DDoS and WAF behavior is defense in depth,
not a replacement for the explicit Auth-route rules.

The ThesisTrace API independently applies short-window authenticated rate
limits by User and Personal Workspace to product requests, with stricter
limits on task-creating and state-changing routes. Because the first deployment
runs one API instance on one node, these counters may remain process-local and
reset on restart; the first release adds no Redis or other rate-limit service.
Request Rate Limits return `429` and remain separate from the three Quota
Profile dimensions and their `QUOTA_EXCEEDED` response.

InsForge Auth remains the only credential verifier. Browsers reach its required
public routes through Cloudflare and Caddy, not through the ThesisTrace API, so
ThesisTrace does not receive or log passwords. The deployment does not assume
an undocumented InsForge Auth rate-limit contract.

Caddy accepts `CF-Connecting-IP` and other Cloudflare forwarding metadata only
on connections from the allowed Cloudflare proxy ranges, removes untrusted
client-supplied forwarding values, and passes one normalized client identity to
the application. Logs and traces continue to exclude credentials, tokens, and
email addresses.

The Cloudflare-to-Caddy connection uses Cloudflare `Full (strict)` mode and a
certificate that Cloudflare verifies. Switching the application record to
DNS-only without first changing the origin access policy is not a supported
steady-state or automatic failover path. Cloudflare proxy-address changes,
rate-limit rules, origin access restrictions, forwarded-IP handling, and
direct-origin rejection are deployment acceptance checks.

This decision supersedes ADR-0128. It preserves that ADR's one-Origin routing,
private-service, and Caddy responsibilities while moving the external public
edge and unauthenticated abuse control to Cloudflare. It requires no
third-party Caddy rate-limit module.
