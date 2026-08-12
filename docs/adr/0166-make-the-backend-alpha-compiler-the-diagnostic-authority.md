---
status: accepted
---

# Make the backend Alpha Compiler the diagnostic authority

The backend Alpha Compiler is the sole authority for Formula syntax, identifier,
type, argument, lookback, and admission-budget validity. Authoring may call it
on a debounce to obtain Alpha Diagnostics while the Browser Draft remains local.
Run admission recompiles the submitted Formula within the authoritative server
flow and creates no durable backend resource when an error exists; it never
trusts an earlier browser result. Each Diagnostic
contains a stable reason code, human-readable message, and exact source range,
with structured expected and actual details when relevant. The frontend uses
those results for highlighting and explanation but does not maintain a second
parser or validation verdict, and the API does not collapse compiler findings
to a generic error string.
