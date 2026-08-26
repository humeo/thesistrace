# Hard-cut the MCP tool contract

ThesisTrace publishes one current `/mcp` interface and changes Tool names,
input and output schemas, descriptions, tests, and documentation atomically.
There are no versioned MCP endpoints, deprecated Tool aliases, legacy input
fields, or fallback dispatchers; clients reconnect and rediscover the current
Tool inventory after a contract change.
