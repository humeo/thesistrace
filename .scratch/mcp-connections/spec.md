# MCP connections

**Status:** complete

## Accepted design

Implement prototype A approved in the conversation, with Connection first,
English setup prompts for Codex / Claude Code / other remote clients, tool
discovery, and Researcher-owned app authorizations. The three explanatory
sentences removed in the final browser comments remain absent. No Usage section.

The product route is `/connections/mcp`; `/mcp` remains the protocol endpoint.
The prototype in `codex/mcp-prototype` is design evidence only.

## Contract

- Connection checks perform authenticated MCP initialization and discovery without
  creating Chat state, calling a model, or executing Research tools.
- Server URL comes from deployment configuration; no example URL or demo state.
- Copying a prompt or command never authorizes an app.
- External clients register with the Auth service, use authorization code + PKCE,
  request resource-bound scopes and obtain consent from the current Researcher.
- Auth owns OAuth client, consent, access-token and refresh-token persistence.
  Core verifies external tokens through a bounded private Auth call on every
  MCP request and remains the authority for tool scopes and Research Ownership.
- App access can be revoked only by its owner. Revocation invalidates outstanding
  authorization codes, access tokens and refresh tokens for that app; issuance
  and revocation serialize by client through the existing Auth coordinator.
- Availability, authorization and client online status are distinct. The page
  does not fabricate online status or last-use timestamps.
- Install the current schema only into an empty scope. No migration or
  compatibility path; preserve the existing Development environment.

## Verification

One real browser flow through the final Caddy/Auth/Agent/Core images covers
login continuation, explicit consent, scope-filtered external MCP discovery,
revocation, and desktop/mobile rendering. Database integration checks cover
cross-Researcher isolation, rejected grants, and token lifecycle. Component
checks cover copying without authorization and failed check/revoke states.

Implementation and verification committed in `e2aa976`.
