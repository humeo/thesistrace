# Separate local, test, and production Research Agent authentication adapters

One authorization seam supplies request-local Research Agent identity and
authority to every MCP Tool. Local stdio uses a fixed local-operator identity,
deterministic HTTP tests use a local OAuth issuer, and production HTTP requires
a real OAuth verifier and refuses startup when it is absent; Core gains no User
model, and there is no auth-disabled switch, anonymous fallback, or failed-token
downgrade.
