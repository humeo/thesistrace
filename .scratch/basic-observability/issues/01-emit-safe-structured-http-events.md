# 01 — Emit safe structured HTTP events

**What to build:** Give operators one safe, machine-readable event for every
non-health Core HTTP request. The same delivery establishes the canonical
operational event contract that later Workers and operator commands can use,
while already proving it through a real API request rather than introducing an
unused logging abstraction.

**Blocked by:** None — can start immediately

**Status:** complete

- [x] Every first-party operational event is one UTF-8 JSON object on one line with UTC millisecond timestamp, level, component, and stable lower-snake-case event name.
- [x] The implementation uses Python standard-library logging and one project-owned formatter or event sink without adding structlog, OpenTelemetry, a collector, or an application log file.
- [x] Only the approved correlation and event-context fields can reach output; unknown extras and arbitrary object representations are omitted.
- [x] Each non-health request receives a server-generated, non-persistent HTTP Request ID that is returned in the `X-Request-ID` response header.
- [x] Exactly one `http_request_completed` event records HTTP Request ID, method, normalized route template, status code, and duration for successful, expected 4xx, and failed requests.
- [x] Domain `request_id` remains an idempotency identity, is not renamed or reused as HTTP Request ID, and is absent from the logging allowlist.
- [x] Raw URL, path parameters, query, headers, cookies, authorization values, request body, and response body never appear in the completion event.
- [x] Liveness and readiness requests produce no routine HTTP completion event.
- [x] Expected validation, conflict, not-found, and other domain outcomes produce no stack trace; an unexpected server failure produces one ERROR event with only exception type and sanitized module/function/line frames.
- [x] DEBUG is disabled by default, and the event boundary applies when the application is constructed directly as well as when it is launched by the normal server command.
- [x] Canary tests prove that tokens, credentials, DSNs, Formulae, Hypotheses, physical paths, object keys, raw exception messages, and arbitrary extras do not appear in captured output.
- [x] Contract tests cover valid one-line JSON, required fields, allowed levels, stable request correlation, normalized routes, health exclusion, expected 4xx, and unexpected 5xx through the ordinary fast test lane.
- [x] Existing API behavior and response bodies remain unchanged apart from the new `X-Request-ID` response header.

## Comments

- Parent: Basic Operational Observability.
- Implemented a standard-library JSON event boundary with strict field-specific
  validation, safe exception frames, DEBUG disabled, and no application log
  file or telemetry dependency.
- Installed the boundary in direct FastAPI construction and the normal Uvicorn
  command, including server-generated `X-Request-ID`, normalized routes,
  health exclusion, one completion event, and one sanitized unexpected-failure
  event.
- Initial Standards and Spec review findings were fixed: tests now exercise the
  real default stderr path, all clocks and injected correlations are controlled
  where applicable, sensitive values cannot hide in approved fields, stack
  frames are sanitized before any writer receives them, expected 409 and secret
  canaries are covered, and canonical Data Refresh operation IDs are preserved.
  Both independent re-reviews were clean.
- Verification: focused operational/HTTP architecture lane 38 passed; Ruff
  passed; complete backend fast lane 547 passed with 2 existing deprecation
  warnings; Web typecheck passed; Web shell lane 56 passed.

## Plan

1. Add failing formatter and HTTP contract tests for the allowlisted one-line
   JSON envelope, normalized route completion, generated HTTP Request ID,
   health exclusion, expected 4xx behavior, sanitized unexpected failure, and
   secret canaries.
2. Introduce one small standard-library operational event module that validates
   the stable envelope, filters context by name and type, sanitizes stack frames,
   and configures one idempotent dedicated JSON logger with DEBUG disabled.
3. Install the canonical request boundary when the FastAPI application is
   constructed, emit exactly one completion event per non-health request,
   attach `X-Request-ID`, handle unexpected exceptions once with a safe 500
   response, and disable duplicate Uvicorn access output.
4. Run focused formatter and HTTP tests, Ruff, the complete backend fast suite,
   Web typecheck, and Web shell tests; preserve the clean baseline behavior.
5. Review the complete Ticket 01 diff from its fixed starting commit on
   independent Standards and Spec axes, fix every material finding, rerun
   affected gates, obtain clean re-reviews, check every acceptance criterion,
   update this tracker, and create one Ticket 01 commit.
