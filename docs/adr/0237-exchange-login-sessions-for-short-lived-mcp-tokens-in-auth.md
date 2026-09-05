# Exchange Login Sessions for short-lived MCP tokens in Auth

Auth exchanges an active Login Session for a short-lived, resource-bound built-in Agent token that grants Researcher-scoped access without cancellation or Stop authority. Keeping issuance in Auth and verification in Core lets the Agent act for its Researcher without owning signing keys, durable credentials, or a second identity service.
