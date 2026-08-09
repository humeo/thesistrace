# 15 — Retry and Rerun against the then-current Head

**What to build:** Recalculate the same frozen research question from the
beginning whenever infrastructure retry or a user Rerun starts, selecting the
current Dataset Head at that new Attempt rather than reusing old market data.

**Blocked by:** 14 — Execute each Attempt against its start-time Head.

**Status:** ready-for-agent

- [ ] A transient infrastructure failure creates a new bounded Attempt; when Head changes from A to B between Attempts, retry selects B rather than reusing A's pin.
- [ ] A successful retry Result is canonically equal to a fresh reference calculation over B and contains no Alpha, Factor, Strategy, or publication intermediate from the failed Attempt over A.
- [ ] Only the winning Attempt's Generation and data-through appear in successful provenance; failed Attempt mechanics remain private and never become a fifth Result value.
- [ ] Permanent domain failures, including insufficient Warm-up, do not auto-retry; retry exhaustion and resource exhaustion remain bounded, sanitized, and stable across restart.
- [ ] Restart recovery continues the same ResearchRun with the next fenced Attempt and prevents any stale Attempt from overwriting a terminal outcome.
- [ ] User Rerun creates a new ResearchRun using the selected Run's frozen Definition, Requested Research Dates, and non-data contracts while its first Attempt selects the then-current Head.
- [ ] Rerun request replay returns the same new Run, conflicting reuse is rejected, and the source Run's state, Result, and provenance remain unchanged.
- [ ] Real Core HTTP and Worker acceptance with PostgreSQL, RustFS, a temporary mount, and deterministic failure and Head-move barriers proves retry and Rerun against fresh references; public wording presents Rerun as the same research question on current data, not a replay or mutation of the historical Result.
