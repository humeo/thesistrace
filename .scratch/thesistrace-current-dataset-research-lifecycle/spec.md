Status: ready-for-agent

# ThesisTrace Current Dataset Research Lifecycle

## Problem Statement

As a ThesisTrace research author, I need to choose the dates of my research and
run the same Alpha and Strategy over a short or long Research Period. The
current product instead treats one synthetic test shape as a domain rule: every
dataset must contain 756 Research Sessions, the first 252 are calculation-only,
and the last 504 are always the reported backtest. This prevents ordinary date
selection, makes recent and short research impossible, and forces expensive
fixtures through every test layer even when a scenario needs only a few
sessions.

The current data lifecycle also exposes a user-facing Data Update and models
market data as a permanent immutable release chain selected when a ResearchRun
is created. That model conflicts with the intended product. Data mutation is an
operator responsibility, the running product should consume one validated
Mounted Canonical Data Store, and newly starting calculations should use the
current Dataset Head. ThesisTrace does not need to retain every historical
market-data byte merely to reproduce an old result.

These fixed assumptions leak through Research Definition authoring, Data
validation, ResearchRun admission, the Research Kernel, Result publication,
DailyTrack progression, PostgreSQL records, the Web interface, and tests. The
Core runtime still defaults to Fixture data, the Data page exposes mutation and
release history, and retries continue to use data selected before their
Attempt starts. Real Tushare data, overlap corrections, mounted production
data, and forward-only DailyTrack behavior therefore do not share one coherent
lifecycle.

The result contract must remain deliberately small. Research authors need the
current Factor Summary, Strategy Summary, Strategy Daily Observations, and
Terminal Strategy State, including terminal holdings, cash, and NAV. They do
not need raw Alpha Values, stock-level Labels, daily Factor observations,
orders, fills, or position history retained forever. The existing fixed one-MiB
limit, however, cannot accommodate an arbitrary Research Period without either
silently truncating required results or rejecting otherwise valid longer runs.

Finally, correctness must not be inferred from a return curve alone. Small,
human-computable scenarios must reconcile every session's signals, orders,
fills, cash, holdings, costs, and NAV while separately proving the real runtime,
data refresh, and browser boundaries. The current global 756-session fixture
makes these tests slow and obscures the exact business rule that failed.

## Solution

Make `start_date` and `end_date` required Run inputs in every Research
Definition. Map their inclusive natural-date range to the first and last
Research Sessions inside the range and permit any positive Research Period
length. Derive Calculation Warm-up from the Alpha Expression's Effective Alpha
Lookback, retain the 252-session maximum, and keep Warm-up outside every
reported Factor and Strategy result. Never read beyond the Research Period end
to mature Forward Return Labels. Short valid periods succeed with the existing
nullable Factor metrics and coverage counts, and Strategy ends with Terminal
Valuation while retaining holdings.

Preserve the exact current durable Result payload:
`factor_summary`, `strategy_summary`, `strategy_daily_observations`, and
`terminal_strategy_state`. Give the complete Result Bundle an exact byte budget
of `ceil(research_period_session_count / 504) * 1 MiB`. Publication remains
atomic and fails rather than truncating or hiding a required value.

Replace the permanent user-visible release chain with one Mounted Canonical
Data Store containing validated Data Generations and one atomic Dataset Head.
Service startup reads the mount and never contacts Tushare. An explicit private
Data Operator command can Bootstrap an empty development store with the latest
one natural year or request an asynchronous Data Refresh. Stable deployments
can mount a previously prepared store and restart without downloading data.
The ordinary Web and product API expose only a read-only Data Overview.

Each Data Refresh requests the current data-through session, the nineteen
preceding Research Sessions, and every newly completed Research Session. A
returned overlap value replaces the current value, ordinary absence preserves
the current value, and explicit governing trading-state or lifecycle evidence
invalidates conflicting stored price or turnover data. The operation rebuilds
affected adjusted prices and Liquidity Universe values, validates a complete
candidate Data Generation, and atomically advances the Dataset Head. Failed
candidates leave the old Head readable. No correction diff or user
notification is produced.

Creating a ResearchRun freezes its Research Definition, Requested Research
Dates, field bindings, Strategy and cost rules, and numeric and semantic
contracts, but does not select market data. Each ResearchRun Attempt selects
and pins the current Data Generation when it starts. Retry selects the then
current Head and recalculates from the beginning. A successful Run records the
actual Generation and data-through session in Run and Attempt provenance
outside the four-value Result payload. A DailyTrack freezes the successful
Run's Definition and terminal simulated-account state, catches up every later
Research Session in order, and then continues forward without replaying or
rewriting previously published history.

Compute Liquidity Rank from mean `turnover_amount_cny` over a target 20-session
window. Only instruments already listed at Dataset Coverage Start may use an
expanding one-through-nineteen-session window during the first nineteen
sessions of the entire Dataset Coverage. From the twentieth Dataset session
onward, and for every instrument listed after Coverage Start, ranking requires
twenty governed observations. Refreshing data or advancing the Head never
restarts this expansion.

## User Stories

1. As a research author, I want to enter a natural-date `start_date`, so that I can choose when my research begins.
2. As a research author, I want to enter a natural-date `end_date`, so that I can choose when my finite ResearchRun ends.
3. As a research author, I want both dates saved with my Research Definition, so that later Runs use the dates I authored.
4. As a research author, I want Save to preserve an incomplete Definition while Run requires both dates, so that drafting remains possible without weakening execution validation.
5. As a research author, I want an inclusive date range, so that valid Research Sessions on both requested endpoints are included.
6. As a research author, I want a weekend or holiday endpoint mapped to the first or last Research Session inside the range, so that I do not have to know the exchange calendar before choosing dates.
7. As a research author, I want a reversed date range rejected, so that an invalid Research Period never creates a Run.
8. As a research author, I want a range containing no Research Session rejected, so that an empty calculation is not presented as research.
9. As a research author, I want a range outside Dataset Coverage to fail explicitly, so that ThesisTrace never silently clamps or moves my dates.
10. As a research author, I want any positive number of Research Sessions to be valid, so that there is no hidden 20-, 504-, or 756-session minimum.
11. As a research author, I want no default 252-plus-504 period inserted behind the interface, so that the displayed dates are the dates actually evaluated.
12. As a research author, I want Calculation Warm-up derived from my Alpha Expression, so that simple expressions do not fetch or calculate unnecessary history.
13. As a research author, I want Effective Alpha Lookback to remain capped at 252 sessions, so that expression complexity remains bounded.
14. As a research author, I want insufficient Calculation Warm-up to fail the Attempt explicitly, so that missing history is never filled or hidden.
15. As a research author, I want insufficient Warm-up to leave my Requested Research Dates unchanged, so that the system never changes the research question to make it runnable.
16. As a research author, I want Warm-up sessions used only as calculation inputs, so that they produce no Alpha signals, orders, Factor observations, or Strategy results.
17. As a research author, I want Forward Return Labels bounded by my Research Period end, so that Factor Evaluation never reads future data outside the request.
18. As a research author, I want an unmatured 1-, 5-, or 20-session Label to remain unavailable, so that missing evidence is not fabricated.
19. As a research author, I want a short valid period to succeed with existing `null` metrics and zero valid-session counts, so that sample insufficiency is not reported as numeric zero or infrastructure failure.
20. As a research author, I want the first Research Session to be the all-cash Backtest Start Baseline, so that every Strategy has a clear initial account state.
21. As a research author, I want a signal calculated after session T to be attempted only at T+1 Open, so that the Strategy cannot trade on information from the future.
22. As a research author, I want a Rebalance scheduled only when its execution Open and one later valuation Open both remain inside the Research Period, so that every realized holding interval is observable.
23. As a research author, I want the final Research Session to perform Terminal Valuation without a new Rebalance, so that no order is created without a later holding interval.
24. As a research author, I want terminal holdings retained rather than forcibly liquidated, so that the finite report does not invent an exit trade or exit cost.
25. As a research author, I want one Strategy Daily Observation for every Research Period session, so that the report length matches the dates I requested.
26. As a research author, I want Factor Evaluation and Strategy Backtest to consume the same Final Alpha Cross-Sections inside the Research Period, so that their conclusions use one signal truth.
27. As a research author, I want a Rerun to preserve the selected Run's frozen Definition and Requested Research Dates, so that later Definition edits do not change what is being rerun.
28. As a research author, I want a Rerun's Attempt to use the current Dataset Head, so that rerunning means recalculating the same research question with current data.
29. As a research author, I want repeated execution over the same frozen contracts and Data Generation to be canonically deterministic, so that calculation correctness is testable.
30. As a research author, I want no minimum Research Period inferred from Factor horizons, so that a short Strategy report remains valid even when some Factor summaries are unevaluable.
31. As a research author, I want every successful Result Bundle to retain `factor_summary`, so that I can inspect the Alpha's bounded Factor conclusions.
32. As a research author, I want every successful Result Bundle to retain `strategy_summary`, so that I can inspect return, risk, cost, and exposure conclusions.
33. As a research author, I want every successful Result Bundle to retain `strategy_daily_observations`, so that the reported Strategy path remains available.
34. As a research author, I want every successful Result Bundle to retain `terminal_strategy_state`, so that terminal positions, cash, NAV, phase, and continuation state remain available.
35. As a research author, I want the Result payload to contain exactly those four top-level values, so that this change does not expand durable research storage.
36. As a research author, I want raw Alpha Values and stock-level Labels to remain transient, so that the result does not become an instrument-by-session warehouse.
37. As a research author, I want daily Factor observations, orders, fills, and position history to remain transient, so that the result does not become an execution ledger.
38. As a research author, I want a 1-through-504-session Result Bundle to receive a one-MiB budget, so that the current 504-session capacity remains the baseline.
39. As a research author, I want a 505-through-1008-session Result Bundle to receive a two-MiB budget, so that capacity grows linearly with reported history.
40. As a research author, I want every later 504-session block to add exactly one MiB, so that the storage rule remains predictable at any Research Period length.
41. As a research author, I want over-budget publication to fail atomically, so that a succeeded Run is never truncated or partially visible.
42. As a research author, I want completed Result Bundles to remain readable after their market-data Generation is collected, so that retained conclusions do not depend on retained input bytes.
43. As a research author, I want successful provenance to record the actual Data Generation and data-through session without becoming a fifth Result value, so that the calculation remains auditable without changing the payload.
44. As a product user, I want Data Overview to show Dataset Coverage Start and end, so that I know the natural range available for research.
45. As a product user, I want Data Overview to show the data-through Research Session, so that I know how current the market data is.
46. As a product user, I want Data Overview to show the last successful refresh time when one exists, so that I can judge freshness without seeing operator jobs.
47. As a product user, I want Data Overview to show readiness, so that I know whether new calculations can start safely.
48. As a product user, I want the Data page to be read-only, so that I cannot mutate shared market data accidentally.
49. As a product user, I want no Update button or update polling state, so that an unavailable capability is not presented as a permission error.
50. As a product user, I want no Dataset Release or Data Generation history browser, so that temporary implementation boundaries do not become product resources.
51. As a product user, I want no operator request, attempt, retry, or failure details in the ordinary API, so that operations state remains private.
52. As a product user, I want Data mutation routes absent from the ordinary product API, so that the capability is not merely exposed and denied with authorization.
53. As a product user, I want an empty but valid store reported as not ready, so that missing data is not mistaken for a healthy Dataset Head.
54. As a Data Operator, I want a private non-Web command surface, so that I can mutate data without exposing an admin product.
55. As a Data Operator, I want to Bootstrap an empty development store explicitly, so that service startup never downloads data as a side effect.
56. As a Data Operator, I want development Bootstrap to default to the latest one natural year, so that initial real-data setup is useful without imposing a research-length rule.
57. As a Data Operator, I want to mount a previously prepared store with longer coverage, so that a stable deployment can use fixed production data immediately.
58. As a Data Operator, I want API and Worker restart to read the mounted Head without contacting Tushare, so that restart remains deterministic and offline from the provider.
59. As a Data Operator, I want a malformed existing Head to prevent data-dependent services from becoming healthy, so that corrupt Canonical Market Data is never served as ready.
60. As a Data Operator, I want to start an asynchronous Data Refresh manually, so that data change remains an explicit operation.
61. As a Data Operator, I want no automatic post-close scheduler in V1, so that timing and operational ownership remain clear.
62. As a Data Operator, I want Refresh submission to be idempotent, so that repeated delivery cannot create duplicate concurrent work.
63. As a Data Operator, I want only one conflicting Refresh to own the Head transition, so that concurrent operations cannot race publication.
64. As a Data Operator, I want abandoned Refresh work detected and retryable, so that Worker loss does not leave the data lifecycle stuck.
65. As a Data Operator, I want every Refresh to request the current data-through session plus its nineteen preceding Research Sessions, so that recent provider corrections can be incorporated.
66. As a Data Operator, I want every newly completed Research Session fetched in the same Refresh, so that several missed days can be caught up together.
67. As a Data Operator, I want a returned overlap value to replace the current value, so that current Canonical Market Data follows the latest normalized source response.
68. As a Data Operator, I want ordinary source absence in the overlap to preserve the current value, so that a sparse response does not delete previously valid data.
69. As a Data Operator, I want explicit suspension, listing, or delisting evidence to override conflicting price and turnover rows, so that preservation cannot create an impossible market state.
70. As a Data Operator, I want every new Research Session to pass complete calendar, instrument, price, adjustment, trading-state, and price-limit validation, so that there is no prior value to mask missing required facts.
71. As a Data Operator, I want affected Adjusted Research Prices recomputed after overlap merge, so that a corrected adjustment input cannot leave inconsistent derived prices.
72. As a Data Operator, I want affected Liquidity Universe snapshots recomputed after overlap merge, so that ranks and memberships follow corrected turnover inputs.
73. As a Data Operator, I want a candidate Data Generation built beside the active one, so that collection and validation never mutate the readable Head in place.
74. As a Data Operator, I want the Dataset Head moved atomically only after complete validation, so that readers observe either the old complete state or the new complete state.
75. As a Data Operator, I want collection, merge, validation, storage, or commit failure to leave the old Head unchanged, so that Refresh failure cannot break current research.
76. As a Data Operator, I want an identical candidate treated as a successful no-op without a value-by-value correction report, so that freshness can be recorded without manufacturing a new history resource.
77. As a Data Operator, I want `last_refresh_at` to mean the completion time of the last successful Refresh, including an identical no-op, so that the public freshness timestamp is unambiguous.
78. As a Data Operator, I want sanitized operational logs and attempt status without a per-value correction diff, so that failures remain diagnosable without creating a correction product.
79. As a Data Operator, I want no user notification when overlap data changes, so that data maintenance does not rewrite or alert on historical research.
80. As a Data Operator, I want an active execution's pinned Generation protected from garbage collection, so that a concurrent Head move cannot remove its inputs.
81. As a Data Operator, I want old unreferenced Generations and objects collectable, so that the mounted store does not grow as a permanent version archive.
82. As a Data Operator, I want the current Head and active pins to be the only durable market-data retention roots, so that completed results do not imply permanent input retention while in-flight candidates remain protected only for their operation lifetime.
83. As a research author, I want Run creation to freeze all non-data calculation contracts without selecting a Data Generation, so that queue timing determines current data but not research semantics.
84. As a research author, I want each Attempt to select the latest Dataset Head when it starts, so that queued work uses the current validated data.
85. As a research author, I want one Attempt to pin one Data Generation for its full execution, so that a concurrent Refresh cannot mix inputs inside a result.
86. As a research author, I want a Head move during an Attempt to affect only later Attempts, so that one execution remains internally consistent.
87. As a research author, I want a transient retry to select the then current Head and recompute Alpha, Factor, and Strategy from the beginning, so that partial artifacts from different Generations are never combined.
88. As a research author, I want Run and Attempt provenance separated from the Result payload, so that operational audit metadata does not expand the four-value result.
89. As a research author, I want no user-selectable Data Generation input, so that the Dataset Head remains the single current-data policy.
90. As a research author, I want no promise that an earlier Run's exact market-data bytes can be recovered, so that the platform can collect obsolete Generations.
91. As a research author, I want to start a DailyTrack explicitly from a successful ResearchRun, so that continuous simulation begins only when I choose it.
92. As a research author, I want DailyTrack to freeze the complete seed Research Definition, so that later edits cannot change the tracked strategy.
93. As a research author, I want DailyTrack to inherit terminal cash, holdings, NAV, and Strategy phase, so that it continues the simulated portfolio instead of restarting from cash.
94. As a research author, I want a historical seed to catch up every later Research Session in order, so that the Track reaches the current Dataset Head without skipping accounting days.
95. As a research author, I want one Head advance containing several new sessions processed session by session, so that signals, execution, and valuation retain daily semantics.
96. As a research author, I want each Tracking Advance Attempt to pin its Data Generation, so that catch-up remains internally consistent while data refreshes.
97. As a research author, I want previously published Track orders, holdings, cash, and NAV left unchanged, so that overlap changes affect only results first calculated afterward.
98. As a research author, I want no historical replay or correction notification, so that DailyTrack remains a forward-extending simulated portfolio.
99. As a research author, I want failed Track progression to leave Tracking Head unchanged, so that partial catch-up is never published.
100. As a research author, I want retry to resume from the latest successful Tracking Checkpoint, so that completed sessions are not duplicated.
101. As a research author, I want the Active DailyTrack Limit and terminal Stop behavior preserved, so that this data change does not weaken existing lifecycle bounds.
102. As a research author, I want Definition edits and Reruns to leave an existing Track untouched, so that each Track keeps a stable identity and origin.
103. As a research author, I want the DailyTrack Factor Summary Snapshot to retain its latest-504-signal-session window, so that its rolling summary remains bounded independently of ResearchRun length.
104. As a research author, I want DailyTrack described as simulation rather than broker trading, so that no live-order expectation is created.
105. As a research author, I want Liquidity Rank based on CNY turnover amount rather than share volume, so that ranking reflects traded value.
106. As a research author, I want an instrument already listed at Dataset Coverage Start ranked from the first session's turnover, so that research at a deliberately bounded dataset start is possible.
107. As a research author, I want the second through nineteenth Dataset sessions to use the expanding observations then available, so that the bootstrap rule grows deterministically toward twenty.
108. As a research author, I want Dataset Coverage session twenty and later to require a complete trailing-20 window, so that the exception ends at one global boundary.
109. As a research author, I want an instrument listed after Coverage Start to wait for twenty governed observations, so that every new listing does not receive an artificial maturity shortcut.
110. As a research author, I want confirmed full-session suspension to contribute zero turnover, so that a governed no-trade day remains part of the observation window.
111. As a research author, I want partial suspension to use observed turnover, so that valid trading activity is not replaced with zero.
112. As a research author, I want unexplained missing turnover to invalidate ranking rather than become zero, so that source loss cannot silently change the Universe.
113. As a research author, I want Refresh and Data Generation changes never to reset Dataset Coverage Start, so that liquidity history does not restart during ordinary operations.
114. As a research author, I want Liquidity Rank sorted by mean turnover descending and `instrument_id` ascending on exact ties, so that Top-N memberships remain deterministic and nested.
115. As a platform developer, I want small scenario-specific datasets, so that failures are fast and locally understandable.
116. As a platform developer, I want no standard 756-session test fixture, so that a synthetic data shape does not return as a hidden product rule.
117. As a platform developer, I want the 252-session lookback boundary tested at the Alpha expression or focused numeric seam, so that every product test does not pay for maximum history.
118. As a platform developer, I want each manual Strategy scenario to reconcile orders, fills, cash, holdings, costs, and NAV for every session, so that a plausible return curve cannot hide accounting errors.
119. As a platform developer, I want focused ledger cases for T-to-T+1 timing, suspension, limit-up buys, and limit-down sells, so that blocked execution never becomes a fake fill.
120. As a platform developer, I want focused ledger cases for board-lot rounding, minimum commission, and insufficient cash, so that share quantities and cash remain legal.
121. As a platform developer, I want focused ledger cases for corporate actions, listing, delisting, and historical Universe Membership, so that asset lifecycle changes never create value jumps or future stocks.
122. As a platform developer, I want exact deterministic replay of the same controlled input, so that nondeterministic iteration or serialization is detected.
123. As a platform developer, I want Result budget boundaries tested without full-size market fixtures, so that 504/505 capacity behavior remains fast.
124. As a platform developer, I want real PostgreSQL, RustFS, Mounted Canonical Data Store, API, and Worker acceptance where those boundaries matter, so that integration behavior is not proven by mocks.
125. As a platform developer, I want deterministic Tushare Stub or Replay inputs in default tests, so that correctness never depends on credentials or the public network.
126. As a Data Operator, I want a production-image smoke test to start and restart against a prepared mount without a Tushare call, so that deployment behavior matches the mounted-data decision.
127. As a platform developer, I want ordinary startup and schema migration to preserve and reject unsupported legacy release-bound state, so that cutover never deletes development data implicitly.
128. As a Data Operator, I want legacy development state removed only by a guarded explicit Development Reset, so that the clean cutover boundary cannot run accidentally or in production.

## Implementation Decisions

- Research Definition persistence, Save, Run, detail responses, and the Web
  form gain ISO natural-date `start_date` and `end_date`. Save may retain an
  incomplete draft; Run requires both fields. The authoring-options catalog
  remains limited to fields, operators, and numeric choice bounds.
- Run Action validates required, malformed, and reversed dates before data
  access. It requires a ready Dataset Head, consults that Head's Research
  Calendar and Dataset Coverage only as an admission preflight, and rejects a
  range with no Research Session or a range outside current Coverage without
  creating a ResearchRun. This read does not bind the Head or Generation.
- Rejected Run Action saves the submitted Definition and returns stable issues
  for missing dates, invalid ordering, no Research Sessions, Data not ready, or
  Requested Research Dates outside Dataset Coverage. It does not queue work
  that cannot run against the current Head.
- After selecting its Data Generation, the Attempt maps the inclusive dates
  again and revalidates Coverage, required fields, and in-period facts. A Head
  change between admission and Attempt may therefore produce a terminal domain
  failure, but it never clamps or moves Requested Research Dates.
- Research Period has no minimum beyond one Research Session. ResearchRun,
  Factor, Strategy, Result, and Web response code must not assume 504 reported
  sessions or 756 canonical input sessions.
- Calculation Warm-up is derived from the normalized Alpha Expression's
  Effective Alpha Lookback. The existing 252-session maximum remains part of
  expression validation, not a fixed prefix attached to every Run.
- Warm-up data may precede `start_date`, but Warm-up sessions are excluded from
  the Alpha signal schedule, Forward Return Label signal set, Factor
  observations, Strategy orders, Strategy Daily Observations, and Result byte
  scaling.
- An Attempt that cannot load the complete derived Warm-up fails with an
  explicit insufficient-warm-up failure. It does not shift Requested Research
  Dates or use a partial rolling value. This is a terminal domain failure for
  that Attempt and Run, not an automatically retryable infrastructure failure.
- Forward Return Label horizons remain 1, 5, and 20 Research Sessions. Entry or
  exit outside the Research Period end is unavailable. Summary metrics keep
  the current nullable values and valid-session coverage counts; no new durable
  reason field is introduced.
- Strategy keeps the existing next-Open execution, all-cash baseline,
  accounting, costs, eligibility, Rebalance, and execution constraints. It
  supports one-through-n Strategy Daily Observations and retains the current
  requirement that execution and one later valuation Open fit inside the
  Research Period.
- Terminal Valuation marks existing holdings on the final Research Session and
  publishes Terminal Strategy State without Rebalance, forced liquidation, or
  hypothetical exit costs.
- The Research Kernel Run contract accepts explicit Research Period boundaries
  and derived Warm-up instead of inferring the final 504 sessions. Advance and
  batch execution continue to share one calculation implementation and Numeric
  Execution Contract.
- The durable Result payload remains exactly `factor_summary`,
  `strategy_summary`, `strategy_daily_observations`, and
  `terminal_strategy_state`. The terminal value continues to contain positions,
  cash, NAV, Rebalance phase, pending bounded signal state, and metric
  continuation state.
- Raw Alpha Values, stock-level Forward Return Labels, daily Factor
  observations, raw orders, child orders, fills, and position history remain
  transient. Manual-ledger testing must use the Kernel's calculation output and
  must not turn those values into product storage.
- The Research Kernel calculation output includes one transient per-session
  Strategy Ledger for verification and invariant checks. It records signals,
  intended orders, fills or rejection outcomes, cash, positions, costs, and NAV
  from the same Strategy transition used for the result. It is available only
  at the Kernel contract, is never returned by the product API, and is rejected
  by Result and Tracking Checkpoint publication.
- The complete Result Bundle's exact owned bytes, including its manifest and
  required payloads, must fit
  `ceil(research_period_session_count / 504) * 1,048,576`. The calculation uses
  Research Period sessions only. Publication fails atomically on an oversized
  bundle and never truncates a required value.
- ResearchRun creation freezes Research Definition content, Requested Research
  Dates, stable field bindings, Strategy and cost rules, Numeric Execution
  Contract, and semantic versions. It no longer stores a selected Dataset Head
  or Data Generation in the frozen Run input.
- Field authorability and expression structure are validated at Run admission.
  The Attempt revalidates that its selected Data Generation supplies the frozen
  fields and compatible Dataset Schema before calculation.
- Each ResearchRun Attempt atomically resolves the current Dataset Head when it
  starts, records and pins that Data Generation, and uses it for the complete
  Attempt. A concurrent Head move cannot change the running Attempt.
- A transient retry creates a new Attempt, resolves the then current Head, and
  recomputes Alpha, Factor, Strategy, and Result from the beginning. No failed
  Attempt intermediate may be reused across Generations.
- User Rerun creates a new ResearchRun from the selected Run's frozen Definition
  and Requested Research Dates. Its first Attempt resolves the current Head in
  the same way as any other Attempt.
- ResearchRun and Attempt provenance records the successful
  `data_generation_id` and data-through session. This metadata is outside the
  four-value Result payload. There is no API for choosing or browsing a Data
  Generation.
- Completed Result Bundles and DailyTrack state remain durable even after their
  market-data Generation is collected. Provenance is an audit coordinate, not
  a promise that retired input bytes remain recoverable.
- The Mounted Canonical Data Store owns Canonical Market Data Generations and
  one authoritative atomic Dataset Head manifest. PostgreSQL owns Data Refresh
  receipts and Attempts, active execution pins, Run and Track lifecycle, and
  retained provenance. RustFS continues to own immutable Result Bundles and
  Tracking Checkpoints.
- One short PostgreSQL Data Lifecycle fence coordinates every critical section
  that reads or moves the mounted Head, creates or releases an active pin, or
  removes a Generation. Candidate construction and research calculation happen
  outside this fence; Head selection plus pin creation happen while it is held.
  Refresh commit and garbage collection acquire the same fence, so GC cannot
  remove a Generation between Head resolution and pin persistence.
- An active pin records its owning ResearchRun or Tracking Advance Attempt,
  selected Generation, lifecycle state, and liveness. Terminal execution
  releases the pin, and abandoned-Attempt recovery releases a stale pin only
  after fencing the lost owner. GC treats every nonterminal pin as a retention
  root.
- Canonical tabular data continues to use partitioned Parquet and bounded
  manifests. A Generation is immutable while it is the Head or is pinned by an
  active execution, but it is not a permanent release-chain resource.
- The store exposes one atomic compare-and-swap Head operation over an expected
  Generation. Candidate data is finalized before this operation. Refresh
  recovery reconciles PostgreSQL operation state with the authoritative mounted
  Head after a crash between storage commit and operation completion.
- Garbage collection retains the current Head, every candidate owned by live
  work, and every Generation pinned by an active ResearchRun or Tracking
  Advance Attempt. It may delete every other old Generation and unreferenced
  Physical Data Object. A live candidate is an operation-scoped temporary root,
  not durable history, and stops being a root when its owning operation reaches
  a terminal state.
- Runtime startup reads and validates the configured mount and never invokes a
  remote DataSource. This spec chooses degraded read-only startup with
  `readiness = false` for an empty valid store. It chooses fail-fast health for
  an existing malformed Head, which is never served as ready.
- FixtureDataSource remains a deterministic test adapter only. Tushare is used
  only by the explicit Data Operator Bootstrap and Refresh paths, plus a
  separately invoked credential/live contract gate.
- ADR-0155 leaves the private operations transport open. This spec chooses the
  simplest concrete surface: a versioned Data Operator command entrypoint
  available inside the deployment environment. It is not registered in the
  ordinary HTTP router and has no Web UI.
- The operator entrypoint supports explicit Bootstrap, asynchronous Refresh
  submission, operation inspection, retry, explicit garbage collection, and a
  cutover-only Development Reset. Submission uses an idempotency key;
  PostgreSQL and the Worker retain the existing concurrent-claim, retry-limit,
  abandonment-recovery, and publication-fence properties. Garbage collection
  is never a startup side effect or an automatic Refresh side effect.
- Explicit Bootstrap of an empty development store defaults to the latest one
  natural year and builds the first validated Dataset Head. The default is an
  operator convenience, not a Research Period or Calculation Warm-up rule.
- The Head manifest records Dataset Coverage, data-through session, and an
  internal preparation time. Explicit Bootstrap sets the preparation time at
  Bootstrap completion, and a prepared mounted store must carry its last
  successful preparation time. Preparation time is operator metadata and is
  not presented as a successful Data Refresh.
- Stable deployments may mount a previously prepared compatible Canonical Data
  Store with longer coverage. Normal API, Worker, and container restart never
  Bootstrap, Refresh, or contact Tushare.
- After Bootstrap, a Refresh request range starts at the nineteenth Research
  Session before the current data-through session, thereby covering exactly
  the current final session plus nineteen predecessors, and ends at the latest
  completed Research Session. It includes all missed new sessions.
- Overlap merge distinguishes three cases. A normalized returned value replaces
  the current value. Ordinary absence preserves the current value. Explicit
  governing trading-state or lifecycle evidence wins and removes or invalidates
  any conflicting stored price or turnover observation.
- Newly completed sessions have no preservation fallback and must satisfy the
  complete existing Canonical validation contract for calendars, instruments,
  prices, adjustment factors, trading state, suspension, price limits,
  uniqueness, and required fields.
- Merge dependency analysis recomputes all affected Adjusted Research Prices,
  adjustment-derived values, Liquidity Scores, Ranks, and Universe Membership
  snapshots before candidate validation. It is not limited to mechanically
  rewriting only the requested rows.
- Every successful non-identical candidate produces a validated Data Generation
  and atomically advances Dataset Head. An identical canonical candidate may
  deduplicate to the existing Generation and complete as a successful no-op
  without a per-value comparison report.
- `last_refresh_at` is the completion time of the most recent successful
  operator Refresh, whether it advanced data-through, applied only overlap
  changes, or deduplicated to an identical candidate. Failed attempts do not
  change it. It is nullable and remains `null` before the first successful
  Refresh, including immediately after Bootstrap or mounting a prepared store.
- Refresh may apply overlap changes even when no new Research Session exists.
  It publishes no correction change-set, historical-diff resource, or user
  notification. Sanitized operation status and production logs remain available
  only to the Data Operator.
- Data Refresh remains manual in V1. No scheduler, post-close timer, cron
  ownership, or automatic service-start Refresh is introduced.
- The public product keeps one read-only Data Overview response containing
  Dataset Coverage Start and end, data-through session, `last_refresh_at`, and
  readiness. The refresh time is nullable under the rule above. The response
  contains no Generation identifier, history, preparation time, Refresh
  receipt, Attempt status, or operator failure details.
- The ordinary HTTP API removes Data mutation, Dataset Release list, and Dataset
  Release detail routes. The absence of mutation is verified as a missing route,
  not an authorization response.
- The Data page removes Update controls, 250-ms mutation polling, update outcome
  messages, release identifiers, predecessor chains, and history. It displays
  only the read-only Data Overview and a manual read refresh.
- ResearchRun and DailyTrack public responses replace user-visible Dataset
  Release terminology with Requested Research Dates, data-through provenance,
  and current tracking progress. Internal Generation identity may remain in
  audit metadata but is not linked to a browseable resource.
- DailyTrack activation remains an explicit action on a successful ResearchRun
  and keeps the Active DailyTrack Limit and terminal Stop semantics.
- A DailyTrack freezes the complete Research Definition and begins from the
  seed Result's Terminal Strategy State. It does not create a new all-cash
  baseline.
- Tracking progression no longer follows a Dataset Release predecessor chain.
  It compares the last successful Tracking Checkpoint session with the current
  Dataset Head and processes every not-yet-published Research Session in
  chronological order.
- Each Tracking Advance Attempt pins one Data Generation. If Dataset Head moves
  during the Attempt, the Attempt completes against its pin and a later Advance
  catches up any additional sessions.
- A Tracking Checkpoint is published only after all sessions owned by that
  Advance complete successfully. Failure leaves Tracking Head and prior
  Checkpoints unchanged; retry begins at the last successful Checkpoint.
- Accepted overlap changes never replay or mutate previously published Track
  orders, holdings, cash, NAV, or Factor Summary Snapshots. They affect only
  calculations first performed after the new Head is selected.
- DailyTrack emits no correction notification. Its Factor Summary Snapshot
  continues to use the latest 504 signal sessions; this bounded rolling Track
  rule is independent of ResearchRun length and is not a standard fixture size.
- Liquidity Score remains the mean CNY turnover amount over a target 20 Research
  Sessions. Deterministic Rank remains score descending and `instrument_id`
  ascending, with every supported Top-N cut from the same ordering.
- During only the first nineteen sessions of the entire Dataset Coverage, an
  instrument already listed at Coverage Start uses the one through nineteen
  governed observations then available. The nth Coverage session uses exactly
  n observations.
- From Dataset Coverage session twenty onward, every rankable instrument needs
  the complete trailing twenty governed observations. An instrument listed
  after Coverage Start never receives its own expanding period.
- Confirmed full-session suspension contributes zero turnover, partial
  suspension contributes observed turnover, and unexplained missing turnover
  invalidates the observation window. Refresh and Head advancement never reset
  Dataset Coverage Start.
- This repository is still in the pre-production development phase, so the
  release-bound local product state is not migrated into the new provenance
  model. Cutover uses an explicit operator-approved development reset and fresh
  Bootstrap or prepared mount; it never deletes local state implicitly during
  ordinary startup or schema migration. The implementation does not build a
  dual Release/Generation compatibility layer. Results and DailyTrack state
  created after cutover follow the new durable contracts.
- Development Reset is a deployment-private, destructive cutover operation. It
  is enabled only for an explicitly identified development environment,
  requires an affirmative operator confirmation tied to that environment, and
  removes only legacy Dataset Release, ResearchRun, Attempt, Result, and
  DailyTrack state, their owned RustFS objects, and the explicitly configured
  development data mount. It preserves Research Definition drafts and every
  unrelated PostgreSQL, RustFS, and filesystem scope. It refuses to run in a
  production environment. Ordinary startup and schema migration detect
  unsupported legacy release-bound state, preserve it, and fail with a
  diagnostic directing the operator to the guarded reset or a separately
  managed migration.

## Testing Decisions

- Good tests assert observable domain behavior and invariants, not private
  helper calls, SQL text, implementation call counts, or a return curve alone.
  They use the lowest sufficiently real layer and keep every scenario
  deterministic, isolated, and automatically judged.
- The highest product acceptance seam is the real Core Runtime through public
  HTTP with PostgreSQL, RustFS, a temporary Mounted Canonical Data Store, and
  Worker processing. It verifies Definition dates, ResearchRun/Attempt
  lifecycle, Result publication, Rerun, DailyTrack catch-up, Data Overview, and
  restart behavior in one coherent boundary.
- The private Data Operator command is the highest data-mutation seam. It uses
  real PostgreSQL and a real temporary Mounted Canonical Data Store with a
  deterministic source adapter to verify Bootstrap, Refresh, retry, crash
  recovery, Generation commit, Head atomicity, and garbage-collection roots.
- The public Research Kernel Run/Advance contract is the necessary pure
  calculation seam. Its transient Strategy Ledger exposes signals, intended
  orders, fills or rejections, cash, positions, costs, and NAV to hand-computed
  tests without making those values durable product data.
- A thin real-browser smoke test proves only the visible boundary: Data is
  read-only; Research Definition requires dates; a short ResearchRun completes;
  its Result renders; and a successful Run can start a DailyTrack. It does not
  repeat the complete backend scenario matrix.
- No additional test-only application seam is introduced. The only new
  high-level interface is the real private Data Operator command required by
  the product boundary itself.
- Research date acceptance covers one-session and two-session periods, ordinary
  endpoints, weekend and holiday endpoints, reversed dates, a range with no
  Research Session, partial or complete out-of-coverage ranges, and Requested
  Research Dates that have insufficient Warm-up. It separately proves that an
  unavailable Head is rejected without creating a Run, admission does not pin
  the preflight Head, and Attempt revalidation can produce a terminal domain
  failure after a concurrent Head change.
- Alpha tests derive nested Effective Alpha Lookback, prove Warm-up exclusion,
  exercise the exact 252-session acceptance boundary, and reject 253 or greater
  at the focused expression/numeric layer rather than in every runtime test.
- Factor tests prove 1-, 5-, and 20-session end censoring, no post-end read,
  short-period `null` summaries, zero valid-session counts, and unchanged
  missing-label classification.
- One- and two-session Strategy tests prove one Daily Observation per Research
  Session, nullable sample-dependent summary metrics, no divide-by-zero or
  fabricated zero, and a complete retained Terminal Strategy State.
- Insufficient-Warm-up tests assert the stable terminal domain-failure
  classification and user-visible issue, unchanged Requested Research Dates,
  no partial Result, and no automatic infrastructure retry.
- Strategy manual-ledger tests use the smallest possible Canonical datasets and
  assert each session's signal, intended order, fill or rejection, cash,
  positions, transaction cost, Gross and Net NAV, and Terminal Strategy State.
- Manual-ledger scenarios cover T signal to T+1 execution, full-session
  suspension without a fake fill, upper-limit buy rejection, lower-limit sell
  rejection with the holding retained, Board-Lot Rounding, minimum commission,
  insufficient cash without negative cash, corporate-action continuity,
  listing and delisting without future instruments, historical Universe
  Membership, exact deterministic repeat, and terminal retention without
  forced liquidation.
- Batch-versus-incremental tests feed the same Tracking Origin, frozen Research
  Definition, initial account state, per-session Canonical Market Data, and
  Numeric Execution Contract to reference Run and session-by-session Advance
  and require canonically exact retained results.
- Result projection tests assert the exact four top-level payload values and
  variable Strategy Daily Observation length. Raw Alpha, Label, daily Factor,
  order, fill, and position-history values must be absent from every successful
  durable Result.
- Result budget-policy tests cover at least 1, 504, 505, 1008, and 1009 Research
  Sessions and feed the production owned-byte accounting rule an exact allowed
  byte count and that count plus one. Separate publication integration tests
  pass only legal four-value Results through production projection, canonical
  serialization, and storage, proving an under-budget success and a
  constructible over-budget atomic failure with no truncation or partial
  visibility. The integration sample need not be exactly one byte over, and no
  test-only payload field or large market fixture is introduced.
- ResearchRun integration tests prove that creation does not select data, a
  queued Run sees a Head moved before Attempt start, an in-progress Attempt
  remains pinned across a concurrent Head move, retry selects a newer Head and
  recalculates, provenance records the successful Generation/data-through, and
  failed Attempt artifacts are never mixed or exposed.
- Data source contract tests assert an exact twenty-session overlap plus all new
  sessions, present-value replacement, ordinary-absence preservation,
  governing-state precedence, multi-session catch-up, correction-only refresh,
  identical no-op, and rejection of incomplete new sessions.
- Bootstrap contract tests freeze the operator as-of instant and Research
  Calendar, prove that the default request begins one natural year before that
  instant and ends at the latest completed Research Session, and keep that
  default independent of Research Period length.
- Mounted-store tests distinguish an empty valid store with
  `readiness = false` from a malformed existing Head that fails health. They
  also prove that `last_refresh_at` is `null` after Bootstrap or mounting a
  prepared store, that the internal preparation time is not exposed publicly,
  and that only a successful Refresh sets or advances `last_refresh_at`.
- Derived-data tests correct an overlap adjustment factor and require every
  dependency-affected Adjusted Research Price to be recomputed. Separate
  turnover corrections require all dependency-affected Liquidity Scores,
  Ranks, and Universe Membership snapshots to be recomputed.
- Data commit tests fail collection, merge, derived recomputation, validation,
  object write, Head compare-and-swap, and PostgreSQL completion in turn. Every
  failure must leave one complete readable Head, enough sanitized diagnostics,
  and a retryable or terminal operation state according to the existing retry
  policy.
- Concurrency and recovery tests cover duplicate submission, concurrent claim,
  lost Worker, stale commit, restart reconciliation after Head commit, and a
  Refresh racing ResearchRun and Tracking Advance pins.
- Garbage-collection tests prove that current Head, live candidates, and active
  Attempt/Advance pins cannot be removed, while an unreferenced retired
  Generation can be collected through the explicit operator command without
  making completed Result Bundles or Track state unreadable. Attempt start,
  Head move, and collection races all pass through the Data Lifecycle fence.
- Liquidity tests use a focused 20-session dataset and cover global Coverage
  days 1, 2, 19, and 20; an instrument listed at Coverage Start; an instrument
  listed later; confirmed suspension zero; partial-suspension observed amount;
  unexplained missing invalidation; exact tie-breaking; nested Top-N; overlap
  recomputation; and proof that Refresh does not reset expansion.
- DailyTrack runtime tests activate a short historical seed against a later
  Head, catch up several sessions in chronological order, fail midway without
  moving Tracking Head, retry without duplication, survive a Head move during
  Advance, preserve published history across overlap changes, and use corrected
  data only for results first calculated afterward.
- Public API and browser tests prove that mutation, Release history, and Release
  detail routes are absent; the Data page has no Update control or operator
  state; Definition date errors are visible; and Data Overview exposes only
  coverage, data-through, last successful refresh time, and readiness.
- Startup and Production Image smoke tests mount a prepared compatible store,
  start API and Worker, validate health and readiness, execute a short Run,
  restart services, and prove through a fail-on-call source adapter or network
  isolation that no Tushare access occurs.
- Cutover tests prepare legacy release-bound state and prove that ordinary
  schema migration and startup refuse the unsupported state without deleting
  PostgreSQL rows, RustFS objects, or mounted data. They prove that Development
  Reset requires the development-environment guard and matching confirmation,
  refuses production, removes only the named legacy execution and data scopes,
  preserves Definition drafts and unrelated objects, and then permits a fresh
  Bootstrap or prepared mount.
- Default unit, integration, acceptance, and browser gates never depend on the
  public network or paid credentials. A live Tushare credential and response
  contract check remains an explicit separate operator gate.
- Architecture guards may prevent reintroduction of a public Data mutation
  route, default Fixture runtime, exact-756 Kernel admission, fixed-504 Result
  admission, or release-chain Track progression, but these guards supplement
  rather than replace observable behavior tests.
- Existing ResearchRun atomic-publication, retry/restart, DailyTrack catch-up,
  checkpoint-equivalence, cache-recovery, Tushare adapter, manual Strategy
  ledger, and Core browser tests are the prior art. Their fixed Dataset Release,
  756-session, 504-session, and user-update expectations must be rewritten to
  the new domain contracts rather than copied.

## Out of Scope

- Financial-data ingestion or Refresh. Point-in-Time financial semantics remain
  documented, but financial data is not implemented by this effort.
- Automatic post-close scheduling, cron ownership, or a general job scheduler
  for Data Refresh.
- A public Data mutation API, admin Web page, ordinary-user authorization error,
  or product-visible operator job history.
- Correction diff reports, per-value audit history, historical-data correction
  notifications, or user alerts.
- A permanent Dataset Release chain, user-selectable historical data versions,
  retention of every old market-data byte, or a guarantee that an old Run's
  exact inputs can be reconstructed.
- Replaying, rewriting, republishing, or notifying on historical ResearchRun or
  DailyTrack results after overlap data changes.
- Persisting raw Alpha Values, stock-level Forward Return Labels, daily Factor
  observations, raw orders, fills, or position history, or exposing them
  through the product API. The transient Kernel Strategy Ledger used only for
  calculation verification is the explicit non-product exception.
- A minimum Research Period, fixed 252-plus-504 execution shape, standard
  756-session fixture, silently moved Requested Research Dates, or Labels that
  read after the Research Period end.
- Changing the DailyTrack Factor Summary Snapshot's latest-504-signal-session
  rolling bound.
- Forced liquidation or hypothetical exit costs at ResearchRun end.
- Broker integration, live trading, intraday data, order queues, partial fills,
  capacity, market impact, slippage, or a second Strategy type.
- Qlib integration, another market-data provider, new asset families, or
  financial-factor implementation.
- Hosted User, Personal Workspace, tenant, RLS, RBAC, invitation, or login work.
  Data Operator is a deployment-private boundary rather than a user role.
- A production-grade migration, archive, or provenance mapping for legacy local
  Fixture Release graphs, ResearchRuns, or DailyTracks. Development cutover is
  an explicit reset boundary rather than a compatibility project.
- Preparing a complete long-history production dataset beyond defining the
  compatible mounted-store contract and operator Bootstrap/Refresh behavior.
- Production scheduling, backup, off-site replication, monitoring product, or
  capacity qualification beyond the required mounted-store image smoke test.

## Further Notes

- ADR-0153, ADR-0154, ADR-0155, and ADR-0156 are the authoritative decisions for
  this effort. `CONTEXT.md` supplies the required vocabulary, especially
  Requested Research Dates, Research Period, Calculation Warm-up, Mounted
  Canonical Data Store, Dataset Head, Data Generation, Data Refresh, Data
  Overview, DailyTrack, and Dataset Bootstrap Expansion.
- For ticket generation and implementation of the Core data and research
  lifecycle, this specification is authoritative over conflicting clauses in
  the earlier `thesistrace-v1-research-platform`,
  `thesistrace-bounded-research-storage`, `thesistrace-core-closure`, and
  `thesistrace-local-lifecycle` specifications. In particular it replaces
  fixed one-MiB capacity, fixed 252-plus-504 execution, user Data Update,
  permanent Dataset Release lineage, and historical input-reproduction
  guarantees. It retains the current four-value Result payload, partitioned
  Parquet encoding, atomic publication, and bounded DailyTrack Working Cache
  where they do not conflict with ADR-0153 through ADR-0156.
- The hosted-platform specification remains authoritative for its identity,
  Personal Workspace, tenant, and deployment boundaries. Any of its Core
  Data, ResearchRun, Result, or DailyTrack lifecycle references follow this
  specification instead. No new tracker label is invented for this precedence
  rule.
- The current implementation still contains exact 756-session validation,
  final-504 slicing, fixed one-MiB publication, Run-admission Dataset Release
  binding, public Data Update and release-history routes, Fixture-backed Core
  runtime data, and release-chain DailyTrack progression. Passing existing
  tests without removing those behaviors is not completion of this spec.
- The number 504 remains valid in two deliberately separate places: one MiB per
  504 Research Period sessions for Result capacity, and the latest 504 signal
  sessions in a DailyTrack Factor Summary Snapshot. Neither is a ResearchRun
  minimum or a reason to restore a 756-session fixture.
- “No correction log” means no per-value correction/change-set product. It does
  not prohibit sanitized operational attempt logs, error classifications,
  metrics, or traces needed to run and diagnose Data Refresh safely.
- Publication of this `ready-for-agent` spec does not create implementation
  tickets or begin implementation. Ticket decomposition remains a separate
  explicitly invoked workflow.
