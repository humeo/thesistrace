# Verification — 2026-09-04

Implementation and local Worker delivery verified.

## Behavior

- Internal adapter option `max_attempts=3` means one initial request plus at most
  two retries; the default request timeout remains 30 seconds.
- The real pinned AKShare query continues where a page failed. Successful pages
  are not fetched again. Timeout, connection interruption, truncated transfer,
  invalid JSON, and HTTP 408/429/500/502/503/504 have bounded retry.
- Backoff is 1/2 seconds by default. Valid Retry-After seconds or UTC HTTP dates
  are respected up to a 30-second wait; invalid or longer directives stop the
  request instead of retrying too early. Permanent HTTP and certificate errors
  are not retried.
- Exhaustion preserves successful categories and returns a gap for the incomplete
  category. The old whole-Refresh recovery/publication behavior is unchanged.
- Safe structured retry/failure events record attempt, method, exception type,
  and HTTP status when available. No exception messages, responses or credentials.
- No HTTP schema changes, new dependencies, DB migrations, fallback paths or UI changes.

## Red and green evidence

1. Original adapter suite: **6 passed**.
2. Added the real AKShare second-page ReadTimeout scenario. The new test failed
   because the adapter returned `CNINFO_DISCOVERY_UNAVAILABLE` instead of completing
   the category. After request-level retry, the same test passed and the external
   page sequence was `[1, 1, 2, 2]` (AKShare requests page 1 separately for the count).
3. Added classification, exhaustion and diagnostics cases: **12 failed, 26 passed**
   before completing those behaviors, then **38 passed**.
4. Added HTTP-date Retry-After, diagnostics isolation and result-equivalence cases.
5. Adapter + Tushare Financial + collection + Data Operator entrypoint checks:
   **96 passed**.
6. All adapter tests plus operational-events checks: **172 passed**.
7. `uv --no-cache run --no-sync --offline ruff check src tests`: passed.
8. `git diff --check`: passed.

The regression suite uses a deterministic fake of remote HTTP, runs the installed
AKShare pagination/normalization, and calls the public discovery interface. No
live upstream requests or database changes were used for these checks.

## Final production image

Built with `deploy/core/Dockerfile.backend`; final image:

`sha256:1d626950652fc37812efe0ebe5ca02e8207535343a87ca4f0f22dda465342b19`

Local tag: `thesistrace-cninfo-retry:20260904`.

```sh
docker compose -p thesistrace-cninfo-retry-smoke-20260904 \
  -f .scratch/cninfo-request-retry/compose.smoke.yaml run --rm -T smoke
```

**8 scenarios passed in the final image**: uninterrupted query, timeout recovery,
third-attempt recovery, exhaustion at three, JSON recovery, 503 recovery, 403 no
retry, and Retry-After handling. Results after recovery equal uninterrupted results.
See `image-smoke.jsonl` for the raw safe events. The container had networking
disabled, a read-only root, no database/config credentials, and only the test script
mounted. It was automatically removed; no test-project containers remain.

## Local Worker deployment

- Verified no running or queued Refresh work before deployment, twice.
- Only `thesistrace-dev-data-operator-worker-1` was recreated; other services/data
  volumes were not restarted or removed. No Financial Refresh was submitted.
- Initial startup failed with `WORKER_TUSHARE_TOKEN_INVALID`: Compose did not
  automatically map the shell's existing `TUSHARE_TOKEN` to the Worker variable.
  Stopped the restart loop, then supplied the existing credential via
  `THESISTRACE_TUSHARE_TOKEN="$TUSHARE_TOKEN"` for the Worker recreation. No key was
  printed, written to files, or changed. Future recreation needs the same injection;
  Compose's structural validation alone does not validate runtime credentials.
- Final running image matches the exact image above.
- Final container started `2026-09-04T08:02:07.451586262Z`, with restart count **0**.
- Read the installed public constructor: `timeout_seconds=30, max_attempts=3`.
- New Worker lease started `2026-09-04T08:02:14.036029Z`; heartbeat advanced to
  `2026-09-04T08:02:44.052341Z`, with a valid lease and no startup-error output.
- Prior image is still locally addressable as
  `sha256:decca8f9b0a5ac8675aece10ea928b44eed8c4bff5374f078933ec1d17c4a789`.

## Review / boundaries

- Checked that retries do not use whole-category replay or publish partial pages.
- Checked explicit attempt limits, failed-response close, permanent-error exclusion,
  valid Retry-After bounds, transport restoration and non-blocking safe logging.
- Preserved pre-existing telemetry, frontend, skills-lock and skill-directory changes.
- Historic missing announcements were not repaired by this code deployment; they
  require a new Financial Refresh operation if the Operator wants to fill the gap.
