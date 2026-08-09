# 15 — Retry and Rerun against the then-current Head

**What to build:** Recalculate the same frozen research question from the
beginning whenever infrastructure retry or a user Rerun starts, selecting the
current Dataset Head at that new Attempt rather than reusing old market data.

**Blocked by:** 14 — Execute each Attempt against its start-time Head.

**Status:** complete

- [x] A transient infrastructure failure creates a new bounded Attempt; when Head changes from A to B between Attempts, retry selects B rather than reusing A's pin.
- [x] A successful retry Result is canonically equal to a fresh reference calculation over B and contains no Alpha, Factor, Strategy, or publication intermediate from the failed Attempt over A.
- [x] Only the winning Attempt's Generation and data-through appear in successful provenance; failed Attempt mechanics remain private and never become a fifth Result value.
- [x] Permanent domain failures, including insufficient Warm-up, do not auto-retry; retry exhaustion and resource exhaustion remain bounded, sanitized, and stable across restart.
- [x] Restart recovery continues the same ResearchRun with the next fenced Attempt and prevents any stale Attempt from overwriting a terminal outcome.
- [x] User Rerun creates a new ResearchRun using the selected Run's frozen Definition, Requested Research Dates, and non-data contracts while its first Attempt selects the then-current Head.
- [x] Rerun request replay returns the same new Run, conflicting reuse is rejected, and the source Run's state, Result, and provenance remain unchanged.
- [x] Real Core HTTP and Worker acceptance with PostgreSQL, RustFS, a temporary mount, and deterministic failure and Head-move barriers proves retry and Rerun against fresh references; public wording presents Rerun as the same research question on current data, not a replay or mutation of the historical Result.

Implementation evidence:

- `9082776 test(research-runs): prove retry on current data` replaces the
  Release-bound retry/recovery/Rerun acceptance with current-Head assertions
  and makes the product action explicit as “Rerun on current data”.
- `2ca5eb5 test(research-runs): use real worker recovery barriers` moves the
  recovery, stale-fence, resource-exhaustion, and Rerun journeys through the
  production Worker process and recognizes PostgreSQL's standard
  `out_of_memory` failure as bounded resource exhaustion.
- `9cc37c3 test(research-runs): isolate worker failure barriers` gives every
  blocked Worker a unique PostgreSQL identity, exact advisory-lock matching,
  bounded diagnostics, and complete process/trigger/lock cleanup.
- Focused acceptance passed 5 Ticket scenarios; the adjacent
  ResearchRun/Head/date/lifecycle slice passed 22 tests. Ruff, compileall, and
  Web TypeScript checks passed. Both fixed-point review axes reported no
  material findings.
