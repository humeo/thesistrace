Status: ready-for-agent

# ThesisTrace V1 Reproducible Research Platform

## Problem Statement

An A-share quantitative researcher needs one system that turns a post-close
investment hypothesis into a reproducible Alpha evaluation, a realistic but
bounded Strategy Backtest, and a continuously advancing DailyTrack. Existing
research workflows often mix mutable market data, unclear adjustment
coordinates, inconsistent factor and portfolio timing, ad-hoc formulas, and
reports that cannot be traced back to exact inputs. That makes an apparently
good Alpha difficult to verify, compare, reproduce, or continue after the
original backtest.

ThesisTrace starts as a greenfield product. V1 must prove the complete chain
from Tushare ingestion through immutable Dataset Release, frozen Research
Definition, transient Alpha calculation, Factor Evaluation, Strategy Backtest,
and Daily Tracking. The same research semantics must produce canonically exact
results whether replayed in batch or advanced one Research Session at a time,
without turning stock-level intermediates into an unbounded result store.

## Solution

Build one single-node Web Workspace for one operator. The Workspace ingests and
validates the required post-close Tushare data into cumulative logical,
immutable Dataset Releases backed by reusable immutable Physical Data Objects.
The operator authors one structured Research Definition Draft, selects a
Liquidity Universe and bounded Alpha Expression, optionally enables historical
industry neutralization, and requests Run. The request validates and freezes
the Draft, pins a concrete Dataset Release and numeric/runtime contracts, then
creates one ResearchRun.

The ResearchRun evaluates transient Alpha Values and Forward Return Labels over
exactly 756 Research Sessions, reports compact Factor Evaluation summaries and
Strategy Backtest results over the final 504 sessions, and atomically publishes
one immutable Result Bundle no larger than 1,048,576 exact bytes. The bundle
retains the Strategy Daily Observation series but not the Alpha Matrix,
stock-level Labels, daily Factor observations, Factor curves, or raw execution
details.

From a successful Run, the operator can explicitly start one continuous
DailyTrack. Each later Dataset Release incrementally advances that Track through
immutable Checkpoints while preserving its fixed Tracking Origin, account
state, rebalance phase, provenance, and bounded Factor Summary Snapshots. A
latest-only, non-authoritative Working Cache retains only the bounded pending
Alpha and rolling aggregate state needed for the next Advance and can be
rebuilt from immutable truth. A historical data correction continues in the
same Tracking Generation and records a visible Tracking Correction Boundary;
only a result-changing calculation-kernel correction creates and fully replays
a new Generation.

The product exposes all authoring, publication, execution, result, diagnostic,
and tracking workflows through a Web UI backed by public application APIs.
Fixture-backed acceptance exercises the same APIs, durable metadata store,
immutable object store, worker lifecycle, calculation kernel, result-size
budget, and cache-recovery behavior as the running product. V1 defines the
single-operator quantitative-research product contract; a Hosted V2 deployment
may wrap those APIs with hosted identity, isolation, scheduling, and operations
without changing the V1 research semantics.

## User Stories

1. As the operator, I want one Web Workspace containing all research resources, so that I can operate ThesisTrace without tenant or organization setup.
2. As the operator, I want deployment-level access control to remain outside the application domain, so that V1 does not pretend to provide multi-user security.
3. As the operator, I want the Workspace to show the current Dataset Release and publication state, so that I know which completed market session is available.
4. As the operator, I want to bootstrap the required three years of research inputs from Tushare, so that the first ResearchRun has exactly 756 Research Sessions.
5. As the operator, I want normal publication to fetch only new required source slices, so that daily updates do not rescan all historical rows.
6. As the operator, I want publication to fail atomically when required data is invalid or incomplete, so that the prior Dataset Release remains trustworthy.
7. As the operator, I want a later successful publication to catch up every missed Research Session in one real Release, so that the system never fabricates releases that were not available.
8. As the operator, I want accepted historical corrections to wait for the next new-session Release, so that V1 has no correction-only publication path.
9. As the operator, I want every Dataset Release to expose its predecessor, appended session range, correction change-set, schemas, objects, anchors, and checksums, so that its complete provenance is inspectable.
10. As the operator, I want the Bootstrap Release to be an explicit predecessor-free root, so that the release chain is deterministic from its beginning.
11. As the operator, I want immutable Physical Data Objects to be reused across Releases, so that logical immutability does not copy the complete dataset every day.
12. As the operator, I want source responses and normalized Canonical Market Data retained separately, so that upstream evidence and research contracts remain auditable.
13. As a research author, I want Tushare hidden behind Canonical Market Data names, so that Research Definitions never depend on vendor field names.
14. As a research author, I want the Field Catalog to show stable identifiers, definitions, units, time semantics, coverage, and release availability, so that I can understand every usable field.
15. As a research author, I want upstream field additions to require a new Dataset Schema version, so that a frozen research never changes silently.
16. As a research author, I want V1 limited to ordinary SSE and SZSE A-shares, so that all research uses one clear market boundary.
17. As a research author, I want the Research Calendar to be the intersection of SSE and SZSE open days, so that all windows and annualization use one deterministic session sequence.
18. As a research author, I want historical Universe Base Pool snapshots without survivorship bias, so that later delistings do not remove earlier eligible stocks.
19. As the operator, I want Base Pool publication to fail when Tushare evidence cannot determine historical membership, so that the system never guesses listing state.
20. As a research author, I want Top 300, Top 1000, Top 2000, and Top 3000 Liquidity Universes, so that I can choose the breadth of the opportunity set.
21. As a research author, I want liquidity ranked by trailing-20-session mean turnover amount, so that Universe Membership has a clear and reproducible definition.
22. As a research author, I want full-session suspensions to contribute zero turnover without removing the stock from the Base Pool, so that liquidity ranking treats governed absence consistently.
23. As a research author, I want liquidity ties broken by Instrument Identity, so that every cutoff is deterministic and nested.
24. As a research author, I want point-in-time ST and *ST stocks excluded from research eligibility but not from the Liquidity Universe, so that selection and market breadth remain distinct.
25. As a research author, I want historical SW2021 L1, L2, and L3 classifications, so that industry analysis never substitutes current classification for historical membership.
26. As a research author, I want historical industry membership represented as non-overlapping half-open intervals, so that classification changes have unambiguous effective dates.
27. As a research author, I want one mutable Research Definition Draft, so that I can edit a complete research before running it.
28. As a research author, I want the Draft to contain hypothesis, data release selection, Universe, Alpha, neutralization, Strategy, execution, and costs, so that evaluation and backtest assumptions cannot drift apart.
29. As a research author, I want `latest` resolved to one concrete Dataset Release only when I request Run, so that editing is convenient while execution remains reproducible.
30. As a research author, I want Run to validate and freeze the Draft atomically, so that an invalid Draft creates neither a frozen version nor a ResearchRun.
31. As a research author, I want later Draft edits to leave previous frozen versions unchanged, so that existing ResearchRuns preserve their meaning.
32. As a research author, I want Research Definition to remain a structured format rather than a DSL or compiled plan, so that authoring and runtime share one understandable contract.
33. As a research author, I want the Numeric Execution Contract recorded automatically at freeze time, so that reproducibility does not add another user setting.
34. As a research author, I want completion and documentation for the six Alpha-authorable Canonical fields, so that formulas are easy to write correctly.
35. As a research author, I want Alpha Expressions limited to numeric literals, the six fields, arithmetic, parentheses, and the closed function set, so that execution is safe and statically understandable.
36. As a research author, I want unsupported syntax, Python, SQL, conditions, and user functions rejected, so that Alpha cannot escape the bounded engine.
37. As a research author, I want every window argument to be an integer literal from 1 through 252, so that history requirements are statically decidable.
38. As a research author, I want nested Effective Alpha Lookback capped at 252 sessions, so that individual legal windows cannot compose into unbounded history.
39. As a research author, I want invalid arithmetic and incomplete windows to produce Missing Alpha Values, so that the engine never hides missing data through filling.
40. As a research author, I want `float64`, natural logarithm, three-valued sign, and population rolling standard deviation semantics fixed, so that formulas evaluate identically across runs.
41. As a research author, I want no automatic winsorization, clipping, ranking, or standardization, so that every Alpha transformation is explicit.
42. As a research author, I want higher Alpha Values always interpreted as more bullish, so that Factor and Strategy results preserve one direction convention.
43. As a research author, I want neutralization selectable as `none` or `industry`, so that sector control remains an option within the same run type.
44. As a research author, I want industry neutralization to demean within historical industry groups after ST and validity gates, so that excluded observations never contaminate another stock's score.
45. As a research author, I want missing industry membership and groups smaller than two reported as distinct coverage loss, so that neutralization never emits artificial values.
46. As a research author, I want one transient Final Alpha Cross-Section formed before labels are joined, so that Factor horizons and Strategy consume exactly the same Alpha Values without requiring a durable Alpha Matrix.
47. As a research author, I want every ResearchRun to use exactly 252 warm-up and 504 reported sessions, so that comparisons use consistent history.
48. As a research author, I want warm-up inputs to complete Alpha windows without creating reported results or orders, so that calculation history does not leak into performance.
49. As a research author, I want price-based research to use fixed-anchor Adjusted Research Prices, so that corporate-action adjustment remains continuous as the Research Window moves.
50. As a research author, I want execution constraints and fees to use Raw Market Prices and integer shares, so that adjustment does not distort exchange rules.
51. As the operator, I want each Adjustment Anchor owned by the Dataset Release and allowed to predate the 756-session window, so that later publication never rescales historical research.
52. As the operator, I want missing daily bars distinguished between confirmed full-session suspension and unexplained data loss, so that only governed absence can succeed.
53. As a research author, I want partial suspensions with a valid daily bar to use the first traded daily Open, so that all open-based calculations share one coordinate.
54. As a research author, I want Factor Evaluation fixed to 1-, 5-, and 20-session next-open-to-open labels, so that predictive horizons are comparable across all runs.
55. As a research author, I want each label attributed to its Alpha signal session, so that daily cross-sectional metrics align with the signal that predicted it.
56. As a research author, I want missing labels classified as right-censored, confirmed-open-unavailable, or unexplained data failure, so that coverage and corruption are not conflated.
57. As a research author, I want a valid-entry position that terminally delists before exit assigned a -100% label, so that failed investments do not disappear from Factor Evaluation.
58. As a research author, I want daily Rank IC as the primary metric and Pearson IC as secondary, so that ranking quality and magnitude sensitivity are both visible.
59. As a research author, I want standard average-rank Spearman ties and missing constant-array correlations, so that Rank IC matches standard statistical semantics.
60. As a research author, I want at least 30 valid Alpha-label pairs before daily IC or Rank IC is calculated, so that very small cross-sections do not appear meaningful.
61. As a research author, I want daily IC, Rank IC, Five-Quantile, and Top-Bottom observations calculated in canonical signal-session order but retained only long enough to produce the Factor summaries, so that factor stability is measured without publishing daily Factor series or curves.
62. As a research author, I want mean, sample standard deviation, unannualized ICIR, positive fraction, and valid-session count per horizon, so that Factor Evaluation has a complete compact summary.
63. As a research author, I want five Alpha-quantile returns and Top-Bottom Return calculated per valid signal session and reported as per-horizon averages, so that monotonicity and separation remain visible without retaining their daily curves.
64. As a research author, I want equal Alpha ties kept in one quantile by average rank, so that row order never splits equivalent signals.
65. As a research author, I want quantile results to require 30 valid pairs and allow empty groups, so that the report does not manufacture balanced samples.
66. As a research author, I want Factor diagnostics kept separate from executable Strategy portfolios, so that Top-Bottom Return does not imply shorting or trading costs.
67. As a research author, I want one long-only Top-N equal-weight Strategy, so that V1 validates the research chain without portfolio-construction variants.
68. As a research author, I want an explicit Holdings Count from 1 through 100, so that portfolio breadth never depends on a hidden default.
69. As a research author, I want an explicit Rebalance Interval from 1 through 20 sessions, so that any supported periodic schedule can be reproduced.
70. As a research author, I want only scheduled Alpha snapshots to drive complete target recalculation, so that intermediate signals do not create overlapping cohorts.
71. As a research author, I want CNY 10,000,000 recorded as the fixed Initial Cash, so that share rounding, minimum fees, and residual cash are reproducible.
72. As a research author, I want Strategy Backtest to start all-cash at the first report-window Open, so that warm-up signals cannot create hidden positions.
73. As a research author, I want orders from Alpha at session `t` first attempted at the Raw Market Price Open of `t+1`, so that the Strategy cannot trade before the signal exists.
74. As a research author, I want the finite ResearchRun to require one valuation interval after a fill, so that the final Open is a valuation boundary rather than a meaningless Rebalance.
75. As a research author, I want valid orders blocked only by full-session suspension, upper-limit buys, or lower-limit sells, so that the execution model is conservative and explainable.
76. As a research author, I want published session-specific price limits rather than universal percentage assumptions, so that board and rule changes remain data-driven.
77. As a research author, I want eligible orders to fill completely at the daily Open without slippage or partial-fill simulation, so that V1 retains one bounded execution model.
78. As a research author, I want blocked orders cancelled for that Open without retry or substitution, so that later positions reflect only actual scheduled fills.
79. As a research author, I want existing-position eligibility reassessed only at scheduled Rebalances, so that ST, Universe, or Alpha changes do not trigger unscheduled liquidation.
80. As a research author, I want target candidates and buy priority ordered by descending Alpha then Instrument Identity, so that exact Alpha ties are deterministic.
81. As a research author, I want sells executed before buys, so that purchases use only cash actually available after position reductions and costs.
82. As a research author, I want all Strategy decisions based on Net Cash and Net NAV, so that previously paid costs reduce future deployable capital.
83. As a research author, I want buys to remain below their ideal target and never create negative cash, so that the Strategy is unlevered.
84. As a research author, I want Main Board, ChiNext, and STAR Market quantity rules applied explicitly, so that every order uses legal integer Execution Shares.
85. As a research author, I want complete liquidation to permit odd-lot remainders, so that positions are not stranded by partial-sell rules.
86. As a research author, I want oversized logical orders split at board-specific caps, so that Transaction Costs and quantity rules operate on legal Child Orders.
87. As a research author, I want commission, minimum commission, transfer fee, and sell stamp duty recorded in the frozen definition, so that cost assumptions remain reproducible.
88. As a research author, I want Transaction Costs charged per filled Child Order without cent rounding, so that accounting follows the fixed numeric contract.
89. As a research author, I want integer Execution Share Quantity separated from fractional Adjusted Holding Units, so that exchange rules and total-return valuation can coexist.
90. As a research author, I want synthetic Research Settlement based on proportional adjusted value, so that V1 can model total return without reconstructing company actions.
91. As a research author, I want finite decimal rounding residuals deterministic and distinct from Transaction Costs, so that implementation precision never masquerades as economic cost.
92. As a research author, I want held full-session-suspended positions valued by the last real Adjusted Research Price, so that NAV stays defined without inventing a market bar.
93. As a research author, I want held terminally delisted positions written off at zero only after local suspension and delisting evidence is checked, so that missing data is not silently treated as loss.
94. As a research author, I want missing-Open resolution performed only for held instruments whose ordinary price path failed, so that delisting handling does not create a full-universe performance scan.
95. As a research author, I want the selected Liquidity Universe's equal-weight return as Strategy Benchmark, so that performance is compared with the actual opportunity set.
96. As a research author, I want confirmed suspended Benchmark members retained with zero return and terminal delistings assigned -100%, so that benchmark constituents are not redistributed or dropped.
97. As a research author, I want one Open NAV Cycle ordering valuation, pre-trade state, sells, buys, costs, and post-trade state, so that every daily return has a deterministic accounting sequence.
98. As a research author, I want Gross and Net NAV derived from the same fill path, so that cost attribution does not create a second hypothetical portfolio.
99. As a research author, I want cumulative and annualized Gross and Net returns, so that total performance and cost attribution are both visible.
100. As a research author, I want Annualized Return calculated as 252-session CAGR, so that the report does not confuse arithmetic annualization with compound growth.
101. As a research author, I want Benchmark Return and Annualized Excess Return from relative Net wealth, so that compounding against the opportunity set is correct.
102. As a research author, I want Maximum Drawdown with peak, trough, recovery, and unrecovered state, so that loss depth and duration are inspectable.
103. As a research author, I want annualized sample volatility of daily Net Returns, so that zero-return intervals and transaction costs remain in risk.
104. As a research author, I want Sharpe based on daily Net Returns and zero risk-free rate, so that its numerator and denominator are explicit.
105. As a research author, I want Calmar based on Net CAGR and Maximum Drawdown, so that return-to-drawdown performance uses the primary account.
106. As a research author, I want one per-Rebalance Turnover series plus average and annualized Turnover, so that actual portfolio change is visible.
107. As a research author, I want cumulative Transaction Costs, cost ratio, and Gross-minus-Net return drag, so that cost loss is understandable in cash and return terms.
108. As a research author, I want daily Actual Holdings Count plus mean, minimum, maximum, and ending values, so that blocked orders and candidate shortages are visible.
109. As a research author, I want daily Maximum Single-Name Weight plus period maximum and ending values, so that realized concentration is visible without enforcing a cap.
110. As a research author, I want daily Cash Ratio plus mean, maximum, and ending values, so that under-investment is visible without adding a target.
111. As a research author, I want upper-limit buy, lower-limit sell, and suspension rejection counts in the Strategy summary, so that market-state execution failures are separated without retaining rejection-event details.
112. As a research author, I want bounded reason counts for insufficient cash, board-lot, candidate shortage, and ineligibility kept separate from Market Rejections, so that missing orders are explained without persisting raw order diagnostics.
113. As the operator, I want each ResearchRun persisted through queued, running, succeeded, failed, or cancelled states, so that execution survives page reloads and failures are visible.
114. As the operator, I want transient ResearchRun retries recorded as Attempts under the same Run, so that infrastructure retries do not change frozen inputs.
115. As the operator, I want a user rerun to create a new ResearchRun, so that prior results and diagnostics remain immutable.
116. As the operator, I want repeated Run requests protected by an idempotency key, so that delivery retries cannot start duplicate work.
117. As the operator, I want a ResearchRun to succeed only after one complete immutable Result Bundle of at most 1,048,576 exact bytes is atomically published, so that the UI never treats partial or oversized output as truth.
118. As the operator, I want the Result Manifest to bind definition, release, numeric contract, calculation kernel, build, objects, and checksums, so that reproduction has a single authoritative root.
119. As a research author, I want reports and Strategy charts derived from the Result Bundle rather than separate result stores, so that presentation cannot silently diverge from retained truth or imply that excluded Factor curves exist.
120. As the operator, I want to inspect failed and cancelled Attempt diagnostics without exposing partial success, so that operational debugging does not weaken result semantics.
121. As the operator, I want to start a DailyTrack explicitly from a successful ResearchRun, so that continuous tracking never begins from an incomplete result.
122. As the operator, I want the Activation Dataset Release fixed to the seed Run's Release regardless of when I click Start, so that wall-clock delay cannot change the account path.
123. As the operator, I want Generation 0 rooted in the seed Result Bundle and kernel version, so that activation reuses verified historical work without copying or mutation.
124. As the operator, I want an older seed Run to catch up through actual Release predecessors, so that missed calendar time is replayed rather than skipped.
125. As the operator, I want a scheduled final seed signal retained only when its execution Research Session is after the Activation Release, so that finite-run cutoff and continuous tracking meet deterministically.
126. As the operator, I want DailyTrack to retain its original all-cash baseline, schedule anchor, holdings, cash, costs, Benchmark, bounded pending-label state, and rebalance phase, so that it is one continuous simulated account.
127. As the operator, I want each new Research Session processed Open first and close second, so that pending orders execute before the new Alpha signal is created.
128. As the operator, I want an active DailyTrack to continue beyond the standard Run's terminal cutoff, so that each valid tracking signal can wait for its future Open.
129. As the operator, I want to stop a DailyTrack without deleting its Head or immutable history while deleting its rebuildable Working Cache, so that future Advances cease and non-authoritative storage is reclaimed without losing published truth.
130. As the operator, I want each Track Advance identified by Track, Generation, and target Release, so that repeated delivery is idempotent.
131. As the operator, I want failed or cancelled Advance Attempts to leave a retryable blocked Advance, so that transient execution failure does not create another logical update.
132. As the operator, I want a successful Advance to atomically publish one immutable Tracking Checkpoint, so that Head never points at partial state.
133. As the operator, I want a failed Advance to leave the prior Head unchanged and not invalidate its Dataset Release, so that data publication and tracking failure are isolated.
134. As the operator, I want a blocked frontier resolved before later Releases advance in that Generation, so that session order cannot be skipped.
135. As the operator, I want a catch-up Release processed session-by-session in chronological order inside one Advance, so that observations retain real provenance without invented Releases.
136. As a research author, I want pending 1-, 5-, and 20-session labels resolved at `t+2`, `t+6`, and `t+21`, so that Daily Tracking follows the same Factor timing as batch evaluation.
137. As a research author, I want matured Labels consumed transiently as valid returns, terminal -100%, or governed unavailability and then discarded at stock level, so that earlier Result Bundles and Checkpoints remain unchanged without accumulating Label events.
138. As a research author, I want Daily Tracking calculate daily IC, Rank IC, quantile, and Top-Bottom observations when Labels mature and keep them only in the bounded rolling Working Cache, so that predictive summaries stay current without publishing Factor curves.
139. As a research author, I want each Checkpoint publish Factor Summary Snapshots over the latest 504 signal sessions, so that continuous tracking retains the standard report-window scale.
140. As the operator, I want a historical correction that affects a Track to continue through an ordinary Advance in the same Generation, so that adding one corrected Release does not force a full replay.
141. As the operator, I want the first Advance using corrected data to record a visible Tracking Correction Boundary and its target Dataset Release, so that the intentional as-operated discontinuity remains auditable.
142. As the operator, I want previously published Strategy observations, Factor summaries, pending decisions, and account state left unchanged across a historical correction, so that immutable history is not silently repaired.
143. As the operator, I want the ordered Dataset Release identities bound by the Checkpoint chain to define correction-aware reproduction, so that verification applies each Release at the same Advance boundary.
144. As the operator, I want corrected historical inputs used only for values first calculated at or after the Tracking Correction Boundary, so that old committed signals still execute as committed.
145. As the operator, I want only a result-changing calculation-kernel correction to create and fully replay a new Generation at the current Head Release, so that one Generation never mixes calculation kernels while data corrections remain inexpensive.
146. As the operator, I want the DailyTrack's Numeric Execution Contract fixed and each Generation's calculation kernel version fixed, so that a single batch oracle can reproduce the chain.
147. As the operator, I want integer, Decimal, and binary64 values canonically serialized for checksums, so that cross-process equality does not depend on display formatting.
148. As the operator, I want negative binary64 zero normalized and non-finite numeric results rejected, so that checksum equality is canonical.
149. As the operator, I want explicit equivalence verification to replay from the same Tracking Origin and ordered Dataset Release sequence, so that batch and incremental outputs can be compared exactly across correction boundaries.
150. As the operator, I want equivalence failure to fail verification rather than pass under tolerance, so that the primary V1 correctness invariant remains strict.
151. As the operator, I want normal daily Advances to avoid a full-history batch replay, so that correctness verification does not make every post-close update unnecessarily expensive.
152. As the operator, I want the Workspace UI to list and inspect Dataset Releases, Drafts, frozen Definitions, ResearchRuns, Result Bundles, DailyTracks, Advances, and Checkpoints, so that every domain resource is navigable.
153. As a research author, I want the editor to show inline structural, semantic, field-binding, and lookback errors before Run, so that invalid research is easy to correct.
154. As a research author, I want the result view to separate Factor Evaluation from Strategy Backtest while showing their shared Alpha and provenance, so that predictive and portfolio conclusions are not conflated.
155. As a research author, I want Factor summary tables and Strategy charts and tables for NAV, Benchmark, drawdown, Turnover, holdings, concentration, cash, costs, and rejection counts, so that retained conclusions are inspectable without Factor curves or rejection-event details.
156. As the operator, I want the DailyTrack view to show current Head, Generation, lag, blocked frontier, Correction Boundaries, latest Factor summary, and account state, so that ongoing research health is visible without exposing the Working Cache or low-level execution events.
157. As the operator, I want API and UI errors to preserve stable reason codes without exposing source tokens or internals, so that failures are actionable and safe.
158. As the operator, I want Tushare credentials supplied through deployment configuration rather than stored in Research Definitions or result artifacts, so that reproducibility does not leak secrets.
159. As the operator, I want deterministic fixture data to run the complete product chain without a live Tushare account, so that CI and local verification do not depend on vendor availability.
160. As the operator, I want a documented single-node startup and post-close operating procedure, so that I can bootstrap, run research, start tracking, publish later sessions, and inspect failures.
161. As the operator, I want active DailyTracks constrained by the Active DailyTrack Limit, so that incremental tracking remains bounded on V1 capacity.
162. As the operator, I want each active DailyTrack Working Cache bounded to pending Alpha for approximately 21 signal sessions and at most 1,512 rolling Factor observation rows, so that daily advancement does not retain full history.
163. As the operator, I want a missing, interrupted, or basis-mismatched Working Cache discarded and rebuilt from immutable Checkpoints and their ordered Dataset Releases, so that cache loss affects latency but never result truth.
164. As a research author, I want the Strategy Daily Observation series retained while Alpha Values, stock-level Labels, daily Factor observations, raw orders, fills, and rejection details remain transient, so that the report keeps useful portfolio history within a bounded storage contract.

## Implementation Decisions

- Treat V1 as the single-operator quantitative-research product contract exposed through one public application API and one Web UI. Its reference deployment remains a single-node modular monolith with one persistent worker, one transactional metadata database, and one local immutable object store; a Hosted V2 wrapper may replace deployment infrastructure without changing V1 research behavior.
- Use Python managed by `uv` for Tushare ingestion, validation, immutable publication, formula evaluation, vectorized Factor calculations, Decimal Strategy accounting, job execution, and the HTTP API. Use TypeScript managed by `bun` for the Web UI. The V1 research core does not depend on Qlib or a Qlib Provider.
- Use a transactional relational database for mutable control-plane records and lifecycle transitions. Store accepted source payloads, Canonical data partitions, Release manifests, Result Bundles, and immutable Tracking artifacts as content-addressed objects with SHA-256 identities. A manifest commit and mutable head update occur transactionally only after every referenced object exists.
- Keep manifests, configuration, provenance, and bounded summaries in canonical JSON. Store Canonical Market Data and every retained table whose rows grow with Research Sessions, instruments, Rebalances, or aggregate events as partitioned Parquet with ZSTD compression. This spec does not choose the retained Source Evidence payload encoding.
- Keep Dataset Release as a cumulative logical snapshot whose physical manifest may reference its predecessor plus new or corrected objects. Resolve Release state through deterministic predecessor traversal with cached indexes; never materialize mutable “latest” tables as result truth.
- Provide a Tushare source adapter limited to the exact V1 contracts. It reads its token from deployment configuration, applies request throttling and deterministic pagination, preserves accepted source responses, and returns explicit typed source records. Research and tracking code never call the adapter.
- Model Canonical data as versioned Dataset Families for Instrument Identity, Research Calendar, EOD Price, Adjustment Factor, Trading State, Universe Base Pool, Liquidity Universe, ST designation, SW2021 classification, and price limits. Financial, futures, options, and convertible-bond families are not created in V1.
- Publish exactly one stable Field Catalog and schema registry for the V1 fields. A frozen Research Definition stores the resolved stable field identities while authors use short catalog names.
- Represent Research Definition as a versioned structured JSON document with a mutable Draft and immutable frozen versions. Validation is split into structural checks, Alpha parsing and lookback analysis, Dataset Release availability checks, field binding, and cross-field semantic checks. It creates no separately persisted compiled representation.
- Implement Alpha Expression as a restricted parser and evaluator with an explicit grammar, allowlist, function registry, missingness propagation, and deterministic ordered window access. The parser may build an in-memory syntax tree for evaluation but that tree is not a domain artifact or stored plan.
- Use one ordered research kernel that accepts an immutable Release view and frozen Definition, calculates stock-level Alpha Values and Forward Return Labels transiently, and emits retained Factor summaries, Strategy Daily Observations, bounded Strategy aggregates, diagnostics summaries, and Terminal Strategy State. Batch ResearchRun and DailyTrack advancement call the same session-level operations.
- Use columnar in-memory calculations for Alpha and Factor cross-sections, but enforce canonical Instrument Identity ordering before every tie-sensitive or checksum-sensitive operation.
- Use standard binary64 operations for Alpha and statistical outputs under the pinned calculation-kernel semantic version. Use the fixed Decimal context for all Strategy decisions and accounting. Store Missing as explicit validity and reason data, never NaN in authoritative artifacts.
- Implement Strategy as a deterministic state machine around the Open NAV Cycle. Orders, Child Orders, fills, rejection details, and low-level diagnostics are transient execution state; the Result Bundle retains the Strategy summary, Strategy Daily Observation series, bounded Rebalance and execution aggregates, Terminal Positions, and Terminal Strategy State needed for reporting and tracking.
- Persist ResearchRun and Tracking Advance execution Attempts separately from their logical parent lifecycle. Workers claim jobs transactionally, heartbeat, honor cancellation, recover abandoned running attempts, and publish results only on complete success.
- Expose API resources for Workspace summary, Field Catalog, Dataset Bootstrap and Publication, Dataset Releases, Research Definition Drafts and validation, ResearchRuns and Attempts, Result Bundle views, DailyTracks, Advances, Checkpoints, and equivalence verification.
- Keep the Web UI resource-oriented: data status, research editor, run list/detail, Factor summaries, Strategy results, DailyTrack list/detail, and operational diagnostics. UI views read authoritative API resources and never calculate domain results independently. The UI does not expose daily Factor curves or raw rejection-event details, and does expose the retained Strategy Daily Observation series.
- A successful ResearchRun publishes exactly one minimal Result Bundle containing its canonical Result Manifest and provenance, three Factor Evaluation summaries, one Strategy summary, one ZSTD Parquet Strategy Daily Observation table, bounded ZSTD Parquet Rebalance and execution aggregate tables, one ZSTD Parquet Terminal Positions table, and bounded Terminal Strategy State. The exact bytes of all Run-owned manifest and payload objects must total no more than 1,048,576 bytes; publication fails rather than dropping required output or persisting excluded intermediates elsewhere.
- A Dataset Publication commit may enqueue Advances for every active DailyTrack, but it never waits for them. Workers process each Track's Release frontier in order and expose lag or blocking state. The Active DailyTrack Limit governs admission; a blocked frontier still counts as active until its Track is stopped.
- Create a latest-only, non-authoritative Working Cache only when a successful ResearchRun seeds a DailyTrack. It contains pending Final Alpha Cross-Sections for at most the approximately 21 sessions needed to mature the longest Label and at most 1,512 rolling aggregate Factor observation rows for the latest 504 signal sessions and three horizons. Normal Advances calculate only newly added sessions, read at most 252 Canonical sessions for a new Alpha, evict stock-level Alpha after its 20-session Label matures, and retain only the resulting Factor Summary Snapshot in the immutable Checkpoint.
- Bind each Working Cache to the DailyTrack, Generation, immutable basis Checkpoint and checksum, frozen Definition, calculation-kernel version, Numeric Execution Contract, and basis Dataset Release. A missing, interrupted, or mismatched cache is discarded and rebuilt over the same bounded windows from the immutable Activation and Checkpoint chain using its exact ordered Dataset Release sequence. Stopping a DailyTrack deletes the Working Cache after preserving the immutable Head and history.
- Generation 0 starts at the seed Result Bundle. A historical data correction advances in the same Generation from the current Head, preserves all previously committed results, and marks the first affected Checkpoint as a Tracking Correction Boundary bound to its target Dataset Release. Only a result-changing calculation-kernel correction creates a predecessor-free Generation root, fully replays from the Tracking Origin, and atomically replaces the Head after complete publication and equivalence verification.
- Version and record source contracts, Dataset Schemas, research semantics, Numeric Execution Contract, calculation kernel semantics, and runtime build identity independently. A compatibility declaration may change only the build identity inside one Generation.
- Provide deterministic seed fixtures spanning at least 756 Research Sessions, more than 30 instruments, all four supported boards, suspensions, partial suspensions, ST transitions, industry transitions, price limits, delisting, liquidity ties, Alpha ties, missing labels, child-order splits, and one historical correction. The fixture generator may create more instruments for cutoff tests without requiring full live-market scale.
- Make external representations stable and versioned. API errors and retained artifact records use explicit reason codes matching the domain glossary. Display rounding and localization stay outside authoritative calculations and checksums.
- Ship a reproducible local command that starts the API, worker, and Web UI; a fixture bootstrap command; a live Tushare bootstrap/publication command; schema migrations; and an operator runbook.

## Testing Decisions

- Primary acceptance seam: exercise the public application API against the real metadata database, immutable object store, worker, Working Cache store, and deterministic Tushare fixture. One scenario must bootstrap and publish a Release, validate/freeze/run a Draft, inspect the bounded Result Bundle, start a DailyTrack, publish later sessions, advance the Track incrementally, lose and rebuild its cache, cross a historical correction, and prove canonical Batch-Incremental Equivalence using the Checkpoint chain's ordered Dataset Release sequence.
- Browser acceptance seam: drive the running Web Workspace through data status, research authoring, Run, Factor-summary and Strategy-result inspection, DailyTrack start, later publication, and updated tracking state. Assert that Strategy daily history and accepted summaries are visible while daily Factor curves and rejection-event details are absent. Browser assertions cover user-visible behavior and resource navigation, not DOM implementation details.
- Calculation seam: focused table-driven tests call the public calculation-kernel boundary for Alpha, Label, Factor, Strategy, and numeric edge cases. Tests assert retained summaries, Strategy observations, terminal state, and canonical checksums rather than private helper calls or the persistence of transient calculations.
- Dataset publication tests cover root and incremental Releases, predecessor and correction manifests, object reuse, atomic failure, catch-up sessions, source/canonical separation, field/schema immutability, suspension evidence, Base Pool evidence, Universe ranking, adjustment anchors, and no historical scan on the normal daily path.
- Research Definition tests cover Draft mutation, Run-time freeze, idempotent Run creation, `latest` resolution, field binding, complete validation errors, Alpha grammar, function allowlist, literal windows, composed lookback, fixed defaults recorded explicitly, and immutability after later edits.
- Factor tests cover exact next-open Labels, censoring and terminal loss, shared transient Final Alpha Cross-Section, neutralization gates, Rank IC and IC sample rules, average-rank ties, quantile assignment, empty groups, canonical daily calculation order, and per-horizon summary aggregates. They also prove that stock-level Alpha and Labels and daily Factor observations are absent from the published Result Bundle.
- Strategy tests cover the all-cash boundary, Rebalance schedule, terminal cutoff, Open NAV ordering, Net-only decisions, sell-before-buy, board lots, child orders, costs, blocked-order cancellation, retained positions, suspended valuation, terminal write-off, Benchmark, all accepted metrics, Strategy Daily Observations, and Decimal residuals. Raw orders, fills, rejection details, and redundant daily series remain transient even when their bounded summary counts are asserted.
- Result-storage contract tests enumerate every ResearchRun-owned object, reject excluded object kinds, sum exact manifest and payload bytes, and fail publication above 1,048,576 bytes. Capacity tests use the production canonical JSON and Parquet writer rather than estimating serialized size from an alternate representation.
- Lifecycle tests cover persistent Run and Advance identities, Attempt retries, cancellation, abandoned-worker recovery, atomic Result Bundle and Checkpoint publication, Head stability on failure, the Active DailyTrack Limit, stopped-Track cache deletion, Release frontier ordering, and idempotent delivery.
- Tracking tests compare normal incremental advancement with an explicit batch oracle from the same Origin and ordered Dataset Release sequence. They cover catch-up publication, Label maturation and Alpha eviction, 504-session Factor-summary rollover, missing and mismatched cache rebuilds, interrupted cache writes, a historical correction boundary within the same Generation without full replay, and a result-changing calculation-kernel correction that alone creates and replays a new Generation.
- Good tests assert observable domain, API, manifest, and cache-recovery behavior from the highest relevant boundary. Private data structures, SQL statement shape, framework components, and incidental execution order outside the accepted domain sequence are not test contracts.
- Existing deterministic fixture, API lifecycle acceptance, and Run-storage capacity checks are prior art. The revised public API acceptance seam becomes the primary executable specification, while focused production-writer and cache-recovery tests cover contracts that cannot be proved from UI output alone.
- Run focused tests and static checks throughout implementation, then the complete backend, frontend, API acceptance, and browser acceptance suites before code review and commit.

## Out of Scope

- Intraday data, real-time signals, live or paper broker execution, order-book simulation, partial fills, market impact, slippage, and notifications.
- Financial statement ingestion or Alpha fields, complete financial revision reconstruction, futures, options, convertible bonds, B-shares, Beijing exchange securities, funds, preferred shares, and non-CNY markets.
- Qlib, Qlib Provider generation, Qlib `.bin` files, or a custom Qlib adapter.
- AI Chat, AI-generated Alpha workflows, MCP, arbitrary Python or SQL strategies, user-defined formula functions, optimizer portfolios, risk models, shorting, leverage, and external index benchmarks.
- Defining Users, Organizations, Tenants, membership, sharing, RBAC, hosted multi-user collaboration, or application-owned authentication inside the V1 research core. A Hosted V2 product may wrap the V1 APIs with these concerns under its own contract.
- Multiple market-data vendors, fallback providers, source reconciliation, automatic complete-history correction scans, or correction-only Dataset Releases.
- Company-action event reconstruction, broker-exact cash/share accounting, tax-lot accounting, or separate dividend and split ledgers.
- Choosing multiple deployment nodes, distributed queues, external object storage, high-availability failover, horizontal scaling, or production cloud infrastructure as part of the V1 quantitative-research contract.
- Arbitrary Research Windows, arbitrary Factor horizons, arbitrary Initial Cash, configurable risk-free rates, configurable transaction-cost schedules, position caps, or multiple Strategy types.
- Complex monitoring dashboards, paging, alerts, notification delivery, and automatic live scheduling beyond the single-node post-close publication process.
- Persisting or displaying Alpha Matrices, stock-level Forward Return Labels, daily Factor observation series or curves, target-weight histories, raw orders, Child Orders, fills, rejection-event details, or duplicate Strategy daily series outside the canonical Strategy Daily Observation table.
- Automatically replaying a DailyTrack from its Tracking Origin because a normal Dataset Release contains an accepted historical data correction.
- Treating the non-authoritative DailyTrack Working Cache as immutable result truth, a user-visible Factor curve, or part of the per-ResearchRun one-MiB Result Bundle.

## Further Notes

- `CONTEXT.md` is the ubiquitous-language source of truth. Accepted ADRs
  through ADR-0148 define the current V1 research, bounded-storage, correction,
  and Daily Tracking behavior; an ADR marked superseded is historical context
  only.
- The `bounded-research-storage` spec owns the cross-cutting physical storage,
  production-writer, exact-byte-budget, Working Cache ownership, and cleanup
  acceptance contracts summarized here.
- The `hosted-platform-v2` spec owns hosted identity, isolation, quotas,
  scheduling, deployment, and operations. It wraps rather than redefines this
  spec's market, Alpha, Factor, Strategy, Result Bundle, and DailyTrack
  semantics.
- Exact reproducibility is defined by immutable input identity, pinned semantic
  versions, canonical serialization, deterministic ordering, and shared kernel
  behavior. It is not defined by report screenshots or tolerance-only numeric
  comparison.
- Live Tushare acceptance requires deployment credentials and endpoint
  permissions. The deterministic fixture path is mandatory and proves product
  behavior without claiming live-source availability.
