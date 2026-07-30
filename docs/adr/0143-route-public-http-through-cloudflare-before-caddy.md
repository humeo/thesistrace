---
status: accepted
---

# Route public HTTP through Cloudflare before Caddy

Hosted Platform V2 exposes one browser Origin through Cloudflare, with Caddy as the only application container binding public ports and direct-origin traffic rejected. Caddy serves the Web application and proxies only the ThesisTrace API and required InsForge Auth routes, never InsForge Storage, while all data, execution, observability, and administration services remain private. Cloudflare protects unauthenticated Auth routes and the API applies authenticated User and Personal Workspace rate limits so abuse control does not expose infrastructure or replace product quotas.
