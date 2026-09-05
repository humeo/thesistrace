# Own external MCP authorization and revocation in Auth

Auth uses Better Auth's OAuth provider for external client registration,
authorization code with PKCE, signed login/consent continuation, and refresh-token
rotation. External MCP access tokens are opaque, resource-bound, and hashed in
the Auth schema. Core verifies them through a bounded private Auth endpoint on
each request, then applies its existing scope and Research Ownership checks.
This spends one internal call per external MCP request to make revocation and
Researcher deactivation effective immediately, rather than waiting for a
self-contained JWT to expire. The built-in Agent retains its separate,
short-lived Login Session exchange token format; invalid tokens never try the
other verifier.

The Researcher owns consent and revocation. Revoking an app removes its pending
authorization codes, access tokens, refresh tokens and consent together. Issuance
and revocation for the same client serialize through the existing Auth operation
coordinator, preventing an in-flight exchange from recreating revoked access.
Service discovery, app authorization and client online state are separate facts;
the product displays only observed discovery and persisted authorization, and
copying setup instructions changes neither.

Account deactivation and password reset remove external MCP credentials in their
existing credential transaction. Hard Auth secret rotation removes all external
credentials under the exclusive mutation lock. Reactivation never restores prior
consent or tokens.
