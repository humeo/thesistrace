# Publish one OAuth-scope-filtered MCP endpoint

ThesisTrace publishes one `/mcp` endpoint whose request-local Tool inventory is
the intersection of the deployment allowlist and the OAuth grant. The current
authority vocabulary is `research:read`, `research:execute`, `research:cancel`,
`tracking:read`, `tracking:execute`, and `tracking:stop`; Research Batch remains
Research authority, and the interface has no domain-specific endpoints or
client-selected Toolset headers.
