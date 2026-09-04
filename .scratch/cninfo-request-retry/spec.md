# Bounded retries for Financial Announcement Discovery

Status: ready-for-agent

Add request-level retry to the pinned AKShare CNINFO adapter, not whole-category
or whole-Refresh retry. Default to three total attempts (initial plus two retries),
retaining the existing 30-second connection/read timeout and using 1/2-second
backoff. A configurable positive integer `max_attempts` belongs to the internal
adapter constructor; no HTTP schema, UI control, database migration, or fallback.

Retry transient connection/read failures, truncated transfers, invalid JSON, and
HTTP 408/429/500/502/503/504. Do not retry other HTTP rejections, certificate failures,
or deterministic data/shape errors. Respect Retry-After; if it exceeds a bounded
30-second wait or is invalid, stop rather than retry before the server permits it.

Only the failed request is repeated. Failed responses are closed before retry.
Do not publish incomplete category data. Exhaustion still produces a discovery
gap, successful categories continue, and later Refreshes retain their existing
gap-repair behavior. Record safe retry/terminal-failure diagnostics without raw
responses, request headers, exception messages, credentials, or full URLs.

Test at the existing public `AkshareCninfoFinancialAnnouncementSource.discover`
boundary using the real pinned AKShare pagination/normalization and a deterministic
fake of the remote HTTP transport. No live upstream or database in regression tests.
Keep all unrelated current worktree edits unchanged. Do not submit a Refresh.

## Verification

- Baseline adapter tests: 6 passed.
- Red: second-page ReadTimeout followed by a valid response must recover without
  fetching already-completed pages again.
- Green: recovery, bounded exhaustion, HTTP/JSON classifications, Retry-After,
  prerequisite GET, unchanged successful output, and transport restoration.
- Build the backend production image and test the same scenarios in an isolated
  container. Deployment, if performed, must first verify the Worker has no active
  or queued Refresh work and must not resubmit the historical operation.
