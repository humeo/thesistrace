# Exchange Login Sessions for short-lived MCP tokens in Auth

The Auth service exchanges one active Login Session for a short-lived OAuth
access token whose subject is the Researcher ID and whose audience is the one
canonical `/mcp` resource; the deployment configuration bounds its scopes and
omits dangerous cancellation and Stop scopes while the Agent Host has no human
confirmation flow. The Agent Host neither signs nor durably stores the token,
and Core remains the authority for Tool discovery, Research Ownership, resource
state, and idempotency, avoiding both an additional OAuth service and identity
keys inside the Agent runtime.
