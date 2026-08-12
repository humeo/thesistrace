# 11 — Expose financial Alpha and Data readiness

**What to build:** Let an ordinary researcher discover, compose, run, and track
the initial financial product from the Research workspace while understanding
the current Market and Financial Coverage. The interface must remain one
Formula-first research journey and must not expose operator actions, raw
responses, or an unrelated financial-statement product.

**Blocked by:** 10 — Publish Financial Refresh under one Dataset Head.

**Status:** ready-for-agent

- [ ] Data Overview displays Market Coverage and Financial Coverage separately,
  including Financial Coverage Start, observation-through cutoff, last
  successful refresh, revision limitations, and Financial Research Readiness.
- [ ] The UI explains that family Coverage is a dataset property and that a
  missing fact for one company is not the same as an incomplete Financial
  Refresh.
- [ ] The Formula editor discovers the six financial identifiers and cs_rank
  from the authoritative catalog without a frontend-maintained allowlist.
- [ ] Field help exposes stable meaning, unit, latest-full-year or
  latest-reported time semantics, company-type applicability, and missingness.
- [ ] A user can submit one market-financial Composite Alpha and navigate to
  its queued, running, and successful ResearchRun states.
- [ ] A successful Composite Alpha result can start a DailyTrack through the
  existing explicit Track action.
- [ ] Financial Coverage admission errors are presented as actionable
  requested-period feedback, while market-only Formulae remain usable.
- [ ] A blocked financial DailyTrack displays its financial-readiness reason
  and later refresh allows the same Track to catch up.
- [ ] Refreshing or reopening the workspace does not replace the frozen Run or
  Track input with current catalog or data state.
- [ ] Stale catalog or diagnostics responses cannot overwrite newer Formula
  text or falsely mark an invalid Formula ready.
- [ ] The interface adds no company statement explorer, Raw Financial Batch
  browser, arbitrary Canonical query, multi-factor editor, or Data Refresh
  control.
- [ ] Focused frontend tests and a real browser journey verify accessibility,
  catalog-driven authoring, coverage messages, ResearchRun navigation, and
  DailyTrack start.

## Comments

- Parent: Point-in-Time Financial Data and Composite Alpha.
- The Alpha Language and Research Workspace external prerequisite is
  transitively required through Ticket 07.
