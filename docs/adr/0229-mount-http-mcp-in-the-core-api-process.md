# Mount HTTP MCP in the Core API process

The Streamable HTTP `/mcp` adapter runs inside the existing Core FastAPI/ASGI
process, while a local stdio entrypoint uses the same Capability Registry and
module interfaces. ThesisTrace does not add an independently deployed MCP
domain process or move Tool behavior to an edge Worker; an edge gateway may
authenticate, rate-limit, and forward to the one Core implementation.
