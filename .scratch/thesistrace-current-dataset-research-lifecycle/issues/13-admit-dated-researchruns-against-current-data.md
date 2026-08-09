# 13 — Admit dated ResearchRuns against current Data

**What to build:** Validate a Definition's Requested Research Dates against the
current mounted Dataset and queue one immutable research question without
selecting the Data Generation that will execute it.

**Blocked by:** 07 — Select and protect one Dataset Head atomically; 12 — Save and reopen Requested Research Dates.

**Status:** complete

- [x] With syntactically valid ISO dates, a missing date, reversed range, no Research Session, Data not ready, or a range partly or wholly outside current Dataset Coverage saves the submitted Definition as a draft, returns stable actionable issues, and creates no ResearchRun.
- [x] A malformed or wrong-type date fails authoring validation before Dataset Head is read, preserves the last durable Definition revision, creates no ResearchRun, and may remain only as unsubmitted Web input for correction.
- [x] Inclusive ordinary, weekend, and holiday endpoints map to the first and last Research Sessions inside the requested natural-date range without rewriting the publicly retained Requested Research Dates.
- [x] Any positive Research Period length is admissible; no 20-, 504-, or 756-session minimum is inferred from Factor horizons or fixtures.
- [x] Admission uses current Head only to preflight readiness, Coverage, Calendar, field authorability, and expression structure; it does not persist or pin that Head or Data Generation.
- [x] An accepted queued Run freezes the Definition revision, Requested Research Dates, field bindings, Strategy and cost rules, Numeric Execution Contract, and semantic versions while excluding data identity; later Definition edits cannot change that frozen question, and Head may still move before Attempt start.
- [x] Run request replay returns the same Definition revision and queued Run, while conflicting reuse is rejected without a duplicate Run or half-committed revision.
- [x] Public Run HTTP with real PostgreSQL and a prepared temporary mounted store proves rejection, inclusive Calendar mapping, immutable admission, and queued projection; list and detail show Requested Research Dates but no Dataset Release, selected Generation, pin, Attempt, or browse link.
