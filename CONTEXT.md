# ThesisTrace

ThesisTrace turns investment hypotheses into auditable Alpha evaluations,
strategy backtests, and continuous daily research tracking.

## Language

### Deferred Hosted Platform

These terms preserve deferred Hosted V2 vocabulary and are not part of the
active Core model.

**V1 Workspace**:
The historical user-visible boundary of one V1 deployment for one operator. It
has no User, tenant ownership, membership, sharing, or RBAC model.
_Avoid_: Personal Workspace, Tenant, organization, user account

**User**:
An authenticated person who owns exactly one Personal Workspace in the first
hosted release.
_Avoid_: Tenant, account, operator

**Operator**:
The trusted human responsible for running the Hosted Platform V2 deployment.
This administrative authority does not make the Operator the owner of a User's
Personal Workspace or research resources.
_Avoid_: User, Personal Workspace member, Worker service identity, tenant admin

**Personal Workspace**:
The private tenant, ownership, quota, and scheduling boundary for one User's
research resources. It has no additional members or sharing in the first hosted
release.
_Avoid_: User, Organization, shared project, V1 Workspace

**Quota Profile**:
The named set of resource and admission limits assigned to one Personal
Workspace. It is independent of pricing, payment, or subscription status.
_Avoid_: Billing plan, account balance, Compute capacity

**Resource Tombstone**:
The permanent minimal record left when a terminal private research resource is
deleted. It preserves identity, authoritative manifest hash, actor, and deletion
time without retaining the deleted result payload.
_Avoid_: Soft-deleted resource, Result Bundle, garbage-collection marker

**Registration Invitation**:
A single-use, email-bound authorization to register one User and provision that
User's Personal Workspace during the first hosted release. It grants no access
to an existing Personal Workspace or research resource.
_Avoid_: Workspace membership invitation, login token, resource permission

**Auth Session**:
The revocable authenticated relationship between one browser and one User in
the Hosted Platform. It begins only after InsForge verifies the User's identity
and grants no authority beyond that User's product permissions.
_Avoid_: InsForge token, Registration Invitation, User, Personal Workspace

**Hosted Local Acceptance**:
Non-attested evidence that the real Hosted product and service boundaries work
on a constrained development runtime. It cannot qualify a release, open the
Registration Invitation gate, or prove production capacity and recovery.
_Avoid_: Launch Qualification, production readiness, capacity qualification

**Launch Qualification**:
Release-bound, attested evidence that the complete production-like Hosted stack
passes product, isolation, capacity, deployment, and recovery gates on its
qualifying node before Registration Invitations are issued.
_Avoid_: Hosted Local Acceptance, smoke test, build verification

**System Health**:
The operational truth of whether the hosted services can safely accept,
schedule, execute, persist, and serve work. It covers Auth, API, PostgreSQL,
object storage, Temporal, workers, Data Refresh, Activity heartbeats and
timeouts, Task Queues, and capacity pressure rather than host metrics alone.
_Avoid_: Host monitoring alone, Data Health, Quantitative Semantic Health

**Data Health**:
The quality and timeliness of the path from Tushare inputs to the current
Dataset Head. It covers readiness, freshness, expected coverage, schema
validity, calendar consistency, duplicates, unexplained gaps, checksums, and
refresh delay.
_Avoid_: Successful HTTP request, System Health, Alpha performance

**Quantitative Semantic Health**:
The evidence that research computation continues to honor its frozen domain
and numeric contracts across Alpha Matrix, Factor Evaluation, Strategy
Backtest, and Daily Tracking. It covers deterministic same-input regression,
accounting, checksum, missingness, and Batch-Incremental Equivalence evidence
without promising either historical input retention or Alpha profitability.
_Avoid_: Investment-performance guarantee, System Health, Data Health

### Research and Alpha

**Investment Hypothesis**:
A human-readable, optional claim about a market relationship that motivates an
Alpha. It is not required to Save or Run a Research Definition.
_Avoid_: Alpha, factor formula, strategy

**Alpha**:
A versioned, executable definition whose Alpha Expression produces a
cross-sectional score for each eligible instrument at each market session.
Higher scores always express a stronger expectation of higher future return;
the runtime never reverses that direction from historical results.
_Avoid_: Investment hypothesis, Alpha Values, trading signal, strategy

**Alpha Direction**:
The V1 convention that higher Alpha Values are more bullish. A lower-is-better
quantity must be negated explicitly in the Alpha Expression, and Factor
Evaluation preserves the resulting metric signs.
_Avoid_: Automatic factor reversal, absolute IC, inferred direction

**Alpha Expression**:
The bounded expression tree embedded in a Research Definition, composed only
of stable Canonical Market Data Field References, numeric literals, and the V1
Alpha Operator Set. It excludes Python, SQL, arbitrary code, and user-defined
functions.
_Avoid_: Research DSL, Python strategy, SQL query, compiled plan

**V1 Alpha Operator Set**:
The closed, versioned Alpha Expression operation set: arithmetic; `abs`, `log`,
and `sign`; `lag`, `delta`, and `pct_change`; and `ts_mean`, `ts_sum`, `ts_std`,
`ts_min`, and `ts_max`, with every time-series or rolling `n` restricted to an
integer literal from 1 through 252. Industry Neutralization follows expression
evaluation rather than acting as an operator.
_Avoid_: Extensible function registry, user-defined function, strategy rule

**Alpha Numeric Semantics**:
The V1 evaluation contract that converts valid Canonical numeric inputs to
IEEE 754 `float64`, performs no configured intermediate rounding, defines
`log` as natural logarithm, maps `sign` to `-1`, `0`, or `1`, and calculates
`ts_std` as population standard deviation with `ddof=0`. Canonical physical
storage types do not have to be `float64`.
_Avoid_: Decimal Alpha arithmetic, sample rolling standard deviation,
implementation-default rounding

**Numeric Execution Contract**:
The versioned V1 numeric contract frozen by a ResearchRun and by a DailyTrack.
It fixes integer, 34-digit half-even Decimal, binary64, residual, and
canonical-checksum semantics independently of UI formatting or the selected
Data Generation.
_Avoid_: Runtime default precision, report formatting, tolerance-based equality

**Effective Alpha Lookback**:
The farthest market-session distance required by an Alpha Expression after
accounting for nested lag and rolling functions. V1 permits at most 252
Research Sessions, and missing observations do not extend that window.
_Avoid_: Largest individual function argument, last valid observations,
automatic data-range expansion

**Missing Alpha Value**:
The absence of a usable Alpha score caused by missing formula inputs, an
incomplete rolling window, division by zero, an invalid logarithm, NaN, or
infinity under Alpha Numeric Semantics. It is excluded before the Final Alpha
Cross-Section and reported as coverage loss rather than filled.
_Avoid_: Zero Alpha Value, forward-filled score, partial-window result

**Alpha Values**:
The deterministic instrument-by-session scores calculated inside a
ResearchRun or Tracking Advance after each Research Session closes. The fixed
neutralization option determines the one transient Final Alpha Cross-Section
shared by Strategy and Factor Evaluation.
_Avoid_: Alpha, factor definition, trading signal

**Alpha Matrix**:
The logical collection of Final Alpha Cross-Sections evaluated during one
execution. It is transient, shared by Factor Evaluation and Strategy Backtest,
and never published in a Result Bundle or Tracking Checkpoint.
_Avoid_: Durable result object, raw expression output, Strategy signal table,
vendor factor table

### Daily Tracking

**Active DailyTrack Limit**:
The hard maximum of ten active or blocked DailyTracks in the current product.
A stopped Track does not count toward it.
_Avoid_: Quota Profile, total DailyTrack history, Compute concurrency

**Daily Tracking**:
The forward-only simulated-portfolio process that advances an explicitly active
DailyTrack through every later Research Session available at the Dataset Head.
It publishes summaries, retained Strategy observations, and terminal state
without rewriting past results, correction notifications, or real trading.
_Avoid_: Full daily batch replay, persisted Alpha history, live trading,
alerting product

**DailyTrack**:
The stable identity of one continuous, fixed-inception Daily Tracking stream
explicitly started from a successful seed ResearchRun. It freezes the complete
Research Definition, carries cash, holdings, NAV, and Strategy phase, catches
up to the Dataset Head, and then continues forward. It is blocked when its
current target cannot complete and terminally stopped only by an explicit Stop;
editing or rerunning research never mutates it.
_Avoid_: ResearchRun, rolling backtest, mutable latest Definition

**Working Cache**:
The latest-only, non-authoritative Pending Alpha and rolling Factor aggregate
state used to advance one active DailyTrack incrementally. It is bounded,
fenced, rebuildable from the latest successful Tracking Checkpoint plus
currently available Canonical Market Data, and deleted when the Track stops.
_Avoid_: Tracking Checkpoint, Result Bundle, Factor curve, permanent Alpha store

**Tracking Origin**:
The successful seed ResearchRun together with its frozen Research Definition,
Research Period, and Terminal Strategy State from which the continuous
simulation continues rather than starting a new rolling backtest.
_Avoid_: Activation date only, latest rolling R1, Tracking Head

**Activation Checkpoint**:
Generation 0's root immutable DailyTrack state. It has no predecessor,
references the seed Result Bundle, records the seed Attempt's Data Generation
metadata for audit, and carries its Terminal Strategy State, Rebalance phase,
and any bounded scheduled final-session signal, but no Alpha or Label history.
_Avoid_: New all-cash baseline, copied Result Bundle, pending Label store,
historical fake Update

**Tracking Advance**:
One idempotent execution that extends a `(DailyTrack, Tracking Generation)`
through one or more later Research Sessions. Its Attempt pins the current Data
Generation, processes sessions in order, survives failure, and publishes one
Tracking Checkpoint only on complete success.
_Avoid_: ResearchRun rerun, Data Refresh, partial result

**Tracking Advance Attempt**:
One execution attempt under a persistent Tracking Advance, with
`queued -> running -> succeeded | failed | cancelled`. A failed or cancelled
Attempt may be followed by another Attempt under the same Advance identity.
_Avoid_: New Tracking Advance, ResearchRun Attempt, partial Checkpoint

**Tracking Checkpoint**:
The immutable authoritative manifest and state published by a successful
Tracking Advance. It records the Data Generation used for newly calculated
sessions and retains the Factor Summary Snapshot, Strategy deltas, and Terminal
Strategy State without Alpha Values, stock-level Labels, raw orders, or fills.
_Avoid_: Mutable tracker row, attempt log, Result Bundle extension

**Tracking Head**:
The mutable lookup pointer to the latest successful Tracking Checkpoint and
Generation for one DailyTrack. Moving the pointer atomically changes the
current view but never edits any Checkpoint or observation.
_Avoid_: Result truth, mutable Checkpoint, Dataset latest

**Tracking Generation**:
One immutable DailyTrack result branch whose Advances share one calculation
kernel and Numeric Execution Contract. Data changes never rewrite it, while a
result-changing kernel correction creates a new fully executed Generation
without mutating the prior branch.
_Avoid_: Data Generation, partial patch, Dataset Head

**Batch-Incremental Equivalence**:
The core V1 correctness invariant that a reference execution and
session-by-session Daily Tracking from the same Tracking Origin, frozen
Research Definition, initial account state, per-session Canonical Market Data,
calculation kernel, and Numeric Execution Contract produce canonically exact
retained results. It is an engineering comparison over supplied inputs, not a
promise that ThesisTrace permanently retains every historical input.
_Avoid_: Persisted-input requirement, tolerance-only comparison, latest rolling
Run, two calculation kernels

### Strategy Execution

**Strategy**:
Rules that translate Alpha Values into portfolio targets and changes over time.
V1 has one type, `long_only_top_n_equal_weight`, which selects the highest
eligible Alpha Values using the Strategy Candidate Order, targets equal weights,
and leaves unallocated capital as cash without shorting or leverage.
_Avoid_: Alpha, factor, investment hypothesis

**Strategy Candidate Order**:
The deterministic total order `final_alpha DESC, instrument_id ASC` applied to
eligible target candidates at a scheduled Rebalance, used both to select the
first `holdings_count` targets and to prioritize buy deficits after sells. Its
identity tie-break is Strategy-specific and never splits equal Alpha Values
across Factor quantiles.
_Avoid_: Database row order, source-response order, Factor average rank

**Holdings Count**:
The explicit integer `holdings_count` from 1 through 100 in a frozen Research
Definition, bounded by the selected Liquidity Universe size and defining the
maximum number of Top-N equal-weight targets. Fewer eligible candidates produce
fewer targets and residual cash.
_Avoid_: Runtime default, percentage cutoff, guaranteed filled positions

**Initial Cash**:
The CNY 10,000,000 recorded as both Gross NAV and Net NAV at the first Research
Period open, with no Actual Holdings. V1 fixes and records the amount in the
ResearchRun's frozen Definition; first deployment occurs at the next Research
Session's open, and no later contribution, withdrawal, borrowing, leverage, or
negative cash is permitted.
_Avoid_: Runtime default, portfolio NAV, deployable cash after trades

**Rebalance**:
A scheduled Strategy decision that recalculates the complete Top-N equal-weight
target from that signal session's Alpha Values and first attempts the resulting
orders at the next session's open, provided both that open and one later
holding-valuation open remain inside the Research Period. Intermediate Alpha
snapshots remain Factor Evaluation inputs rather than queued or overlapping
Strategy cohorts.
_Avoid_: Delayed execution of every signal, daily signal cohort, Factor label

**Target Portfolio**:
The ideal equal-weight values calculated at a scheduled execution open by
dividing pre-trade Net NAV by the number of selected Top-N targets. It is
translated into eligible sells followed by buy deficits in Strategy Candidate
Order without negative cash, so execution constraints may leave Actual Holdings
different from the target.
_Avoid_: Actual Holdings, guaranteed allocation, Factor quantile

**Actual Holdings**:
The positions and cash remaining after applying order eligibility, costs, and
rounding to a Target Portfolio. The Result Bundle retains daily aggregates and
Terminal Positions rather than target-weight history or unfilled orders.
_Avoid_: Target Portfolio, pending order, ideal equal weight

**Execution Share Quantity**:
The non-negative integer share coordinate changed by filled Strategy orders and
used for Board-Lot Rounding, Child Orders, Raw Market Price notional, and
execution constraints. It is distinct from Adjusted Holding Units and does not
claim to reconstruct broker shares through company actions.
_Avoid_: Adjusted Holding Units, broker share balance, market volume

**Adjusted Holding Units**:
The possibly fractional quantity used to value an Actual Holding as
`units * Adjusted Research Price`, with buys adding `Execution Shares /
Adjustment Scale` and partial sells removing units in proportion to Execution
Shares sold. It represents adjusted total-return valuation rather than broker
shares or a company-action event ledger.
_Avoid_: Execution Share Quantity, Raw Market Price order quantity, stock split

**Research Settlement**:
The synthetic cash value transferred by a Strategy sale, equal to removed
Adjusted Holding Units multiplied by current Adjusted Research Price. It
realizes adjusted total return rather than broker proceeds, while Raw Market
Price notional remains the basis for order rules and Transaction Costs.
_Avoid_: Raw notional, company-action event, broker cash settlement

**Actual Holdings Count**:
The number of instruments with positive Execution Share Quantity after each
open execution cycle, excluding cash but including retained off-target
positions, so it may exceed Holdings Count. V1 retains its daily series plus
mean, minimum, maximum, and ending values.
_Avoid_: Holdings Count target, eligible candidate count, order count

**Maximum Single-Name Weight**:
The largest Actual Holding valuation divided by post-trade Net NAV on one open.
V1 retains the daily series and reports its period maximum, date, and ending
value without enforcing it as a Strategy position limit.
_Avoid_: Target equal weight, configured cap, largest order weight

**Cash Ratio**:
Post-trade Net Cash divided by Net NAV on one open. V1 derives it from Strategy
Daily Observations and retains only its summary aggregates, not a duplicate
series or target.
_Avoid_: Cash target, unfilled ratio, Initial Cash

**Valuation Carry**:
The last valid Adjusted Research Price carried solely to mark a confirmed
full-session-suspended Actual Holding for Strategy NAV, giving zero return until
a real post-suspension mark appears. It is never Canonical Market Data, an Alpha
input, a Forward Return Label, or an execution price, and a partial suspension
with a valid daily bar never uses it.
_Avoid_: Forward fill, synthetic market bar, executable price

**Terminal Delisting Write-Off**:
The conservative Strategy accounting event applied only when an Actual Holding
has no required daily Open, is not governed by confirmed full-session
suspension, and has explicit effective terminal-delisting evidence in the
Attempt's pinned Data Generation. It removes the position at zero value and
zero proceeds without creating an order, fill, Transaction Cost, Turnover,
Market Rejection, or observed zero-price trade.
_Avoid_: Forced sell, suspended-price carry, unexplained missing-data fallback

**Terminal Delisting Return**:
The synthetic `-100%` return produced only after a valid starting Adjusted
Research Price when explicit terminal delisting makes the required Benchmark
or Forward Return Label ending Open unavailable. It cannot apply to a missing
Label entry Open, relies on an on-demand local status lookup, and never treats
zero as a Canonical market price.
_Avoid_: Observed zero-price trade, suspension carry, missing-entry return

**Board-Lot Rounding**:
The conversion of a buy value deficit or proportional sell-value reduction into
a legal integer Execution Share Quantity using Raw Market Price for buys and the
current Execution Shares-to-adjusted-value proportion for sells. Main-board and
ChiNext buys and partial sells use 100-share multiples; STAR Market buys require
at least 200 shares and then permit one-share increments; complete liquidation
sells any odd-lot remainder; below-minimum orders are omitted.
_Avoid_: Fractional share, universal 100-share rule, rounded target value

**Child Order**:
One exchange-quantity-compliant piece of a larger logical Strategy order.
V1 splits at board-specific limit-order caps, applies one common synthetic
next-open eligibility result to all children for the instrument, and charges
Transaction Costs per child without simulating partial fills.
_Avoid_: Partial fill, replacement order, independent execution time

**Transaction Costs**:
The fixed V1 deductions applied to each filled order: 0.0003 all-in broker
commission on both sides with a CNY 5 minimum, 0.00001 transfer fee on both
sides, and 0.0005 stamp duty on sells, with regulatory and exchange handling
fees included in commission rather than deducted separately. Their base is
Execution Share Quantity multiplied by Raw Market Price, and decimal accounting
uses no per-order or per-Child-Order CNY 0.01 rounding despite two-decimal report
formatting.
_Avoid_: Slippage, market impact, double-counted regulatory fee, hidden rate

**Transaction Cost Return Drag**:
Gross Cumulative Return minus Net Cumulative Return from the same fill path,
reported as a percentage-point loss. V1 also reports cumulative cost CNY and
that amount divided by Initial Cash.
_Avoid_: Relative return decrease, percentage of current NAV, annualized drag

**Turnover**:
Half the sum of absolute same-open changes in every actual instrument and cash
weight, with each side divided by its corresponding Net NAV and cash taken from
Net Cash. V1 retains one value per scheduled Rebalance, including zero and
initial deployment, then reports its event mean and
`sum(Turnover) * 252 / return_interval_count` annualization.
_Avoid_: Order count, target-weight change, filled-notional double count

**Rebalance Interval**:
The explicit `rebalance_every_sessions` integer in a frozen Research Definition.
It may be any value from 1 through 20 and determines the distance between
scheduled Strategy signal sessions.
_Avoid_: Natural-day interval, fixed 1/5/20 enumeration, holding cohort

**Open Execution Model**:
The synthetic V1 fill contract that attempts a Strategy order at the next
session's Raw Market Price open, meaning the instrument's first traded daily
price rather than a fixed 09:30 timestamp. It fully fills every otherwise
eligible order without queue, partial-fill, capacity, impact, or slippage;
full-session suspension blocks both sides, an upper-limit open blocks a buy, a
lower-limit open blocks a sell, and unknown or invalid open data fails
Publication or ResearchRun.
_Avoid_: Adjusted execution price, intraday fill model, guaranteed limit fill

**Blocked Order**:
A Strategy order that cannot execute at its one scheduled open under the Open
Execution Model. It is cancelled without retry or candidate substitution, so a
blocked buy leaves cash, a blocked sell leaves the position, and only a later
scheduled Rebalance may create a new order.
_Avoid_: Pending order, partial fill, next-ranked replacement

**Market Rejection**:
One created logical order blocked by `upper_limit_buy`, `lower_limit_sell`, or
confirmed `full_session_suspended` with no daily open. V1 retains bounded
reason counts but no order-level rejection details or unfilled ratio.
_Avoid_: Insufficient cash, below-board-lot omission, data-quality error

**Trading State**:
The one Canonical `equity.trading_state` value for an active instrument and
Research Session: `normal`, `open_suspended_partial`,
`after_open_suspended`, or `full_session_suspended`. Both partial states retain
a first traded daily Open, while only `full_session_suspended` is a Market
Rejection input, permits an absent daily bar, and uses Valuation Carry.
_Avoid_: Missing-data fallback, pending order state, inferred zero turnover

**Held Missing-Open Resolution**:
The conditional local lookup path entered only for an Actual Holding without a
required daily Open, checking Canonical full-session suspension first,
terminal-delisting evidence second, and otherwise reporting unexplained data
loss. A valid daily Open bypasses it, and ResearchRun never calls Tushare per
instrument.
_Avoid_: Daily delisting scan, remote runtime lookup, missing-price zero fill

**Execution Diagnostic**:
A runtime-classified reason why a target or order was not created, such as
insufficient cash, a below-minimum Board Lot, insufficient candidates, or
ineligibility. It is distinct from a Market Rejection and may survive only as
a bounded aggregate.
_Avoid_: Blocked Order, successful fill, silent omission

**Existing-Position Eligibility**:
The scheduled reassessment of whether a current holding remains in Universe
Membership, has a valid final Alpha Value, is not ST or `*ST`, and remains in
the Top-N target set. Failure gives it a zero target at that Rebalance but never
causes an unscheduled liquidation.
_Avoid_: New-buy eligibility, immediate forced sale, permanent eligibility

### Research Lifecycle and Factor Evaluation

**Research Definition**:
The mutable, saved authoring record for one research, containing one Alpha and
its configurable research choices, including required natural-date `start_date`
and `end_date`. It may be incomplete between Save actions; Run saves its
current content and, when valid, freezes that content in a new ResearchRun.
_Avoid_: Draft, frozen Definition resource, ResearchSpec, compiled plan

**Run Action**:
The Research Definition action that saves the submitted current content and
attempts to create a ResearchRun. Rejected content remains saved but creates no
ResearchRun, and accepted content does not select data until an Attempt starts.
_Avoid_: Save followed by Run, Rerun, execution Attempt

**ResearchRun**:
One durable execution request over frozen Research Definition content and
Requested Research Dates. Its successful Attempt produces Factor Evaluation
and Strategy Backtest conclusions and may seed a DailyTrack only after
publishing a complete Result Bundle.
_Avoid_: Research Definition, factor evaluation, backtest

**Rerun**:
The user action that creates a new ResearchRun with the selected Run's same
frozen Research Definition and Requested Research Dates. It ignores current
Definition edits, while the new Run's Attempt independently selects the latest
Dataset Head when it starts.
_Avoid_: ResearchRun Attempt, Run Action, modified research

**ResearchRun Attempt**:
One infrastructure execution attempt belonging to an existing ResearchRun,
which pins the latest Data Generation when it starts and recomputes the whole
Run from the beginning. A retry creates another Attempt, may select a newer
Generation, and never mixes partial artifacts; a user-requested rerun is a new
ResearchRun.
_Avoid_: ResearchRun, user rerun, modified run input

**Result Bundle**:
The immutable, minimal authoritative result of one successful ResearchRun. It
retains exactly `factor_summary`, `strategy_summary`,
`strategy_daily_observations`, and `terminal_strategy_state`. Its byte budget is
`ceil(research_period_session_count / 504) * 1 MiB`; Alpha Values, stock-level
Labels, daily Factor observations, orders, fills, and position history remain
excluded.
_Avoid_: Alpha store, UI cache, partial report, mutable result, attempt
diagnostics

**Result Manifest**:
The immutable index and provenance record at the root of a Result Bundle. It
identifies every required result object and checksum and records the successful
Attempt's Data Generation and data-through session so the bundle can be
validated and audited without promising that the input bytes remain available.
_Avoid_: Data Generation manifest, HTML report, job log

**Factor Evaluation**:
The Research-Period-bounded summary that assesses whether an Alpha has
predictive and ranking value independently of a Strategy's realized portfolio
outcome. V1 evaluates the same transient Alpha Values at fixed 1-, 5-, and
20-market-session horizons and retains summary statistics and coverage counts,
but no daily Factor observations, Alpha Values, or Forward Return Labels. A
short valid period may produce `null` summary metrics and zero valid-session
counts without failing the ResearchRun or fabricating a numeric zero.
_Avoid_: Factor curve, Alpha Matrix, Strategy Backtest, factor return

**Label Maturation**:
The calculation point when one pending signal-session and horizon Label becomes
resolvable because its nominal exit Research Session is available to the
calculation. A ResearchRun never reads after its Research Period end; Daily
Tracking may consume later sessions to update a Factor Summary Snapshot without
persisting a stock-level event.
_Avoid_: Stored Label row, in-place Label update, signal-date rewrite

**Factor Summary Snapshot**:
The immutable per-horizon Factor summary published by one Tracking Checkpoint
over the latest 504 signal sessions using observations mature and valid at
that Checkpoint. It retains no daily observations, Alpha Values, or Forward
Return Labels.
_Avoid_: Factor curve, growing observation store, mutable ResearchRun report,
daily IC result

**Rank IC**:
The daily cross-sectional standard Spearman correlation between valid final
Alpha Values and one Forward Return Label horizon, with exact ties receiving
their average ascending rank rather than an identity or row-order tie-break. It
is V1's primary Factor Evaluation metric, yields no value for a constant Alpha
or Label array, and is aggregated across sessions without pooling stock-day
rows.
_Avoid_: Pearson IC, time-series correlation, pooled correlation

**IC**:
The daily cross-sectional Pearson correlation between valid final Alpha Values
and one Forward Return Label horizon. It is a secondary Factor Evaluation
metric and retains sensitivity to score and return magnitudes.
_Avoid_: Rank IC, regression coefficient, pooled correlation

**ICIR**:
The arithmetic mean of a valid daily IC or Rank IC series divided by its sample
standard deviation. V1 reports it separately for each Forward Return Label
horizon without annualization; a zero or missing denominator yields no ICIR.
_Avoid_: Annualized strategy information ratio, t-statistic, pooled IC

**Effective Factor Sample**:
The instruments produced by one signal session's Final Alpha Cross-Section that
also have a valid Forward Return Label for one independently filtered horizon,
without changing that Final Alpha Cross-Section. V1 requires at least 30 pairs
and non-constant Alpha and Label cross-sections for IC and Rank IC; otherwise
the session metric is sample-insufficient.
_Avoid_: Universe Membership, Strategy holdings, filled missing observation

**Final Alpha Cross-Section**:
The one instrument-to-score set produced for a signal session after Universe
Membership, point-in-time ST exclusion, strict Alpha Expression validation,
and, when selected, historical-industry coverage, minimum-group-size filtering,
and equal-weight demeaning. It exists before Forward Return Labels are joined
and is shared unchanged by Strategy Backtest and the 1-, 5-, and 20-session
Factor Evaluation sections.
_Avoid_: Horizon-specific Alpha, raw expression output, Effective Factor Sample

**Five-Quantile Return**:
The equal-weight Forward Return Label of each of five approximately equal-count
groups formed daily by sorting the Effective Factor Sample from lowest Alpha
Values in Q1 to highest in Q5. Equal values share average rank `r` and group
`ceil(5 * r / N)`, so groups may differ or be empty without rebalancing; fewer
than 30 valid pairs make the complete session-horizon result missing, and the
result is a Factor diagnostic rather than portfolio NAV.
_Avoid_: Sorting by future return, Strategy holding, cumulative backtest return

**Top-Bottom Return**:
The Factor diagnostic `Q5 return - Q1 return` for one signal session and
Forward Return Label horizon. It measures separation between high- and
low-Alpha groups without asserting that Q1 can be shorted or applying Strategy
costs.
_Avoid_: Executable long-short portfolio, Strategy excess return, net return

**Forward Return Label**:
The Adjusted Research Price return attributed to Alpha signal session `t`,
starting at the `t+1` Open and ending at the `t+1+h` Open for the fixed
1-, 5-, or 20-session horizon. Governed suspension, censoring, missingness, and
terminal-delisting rules determine availability, and the stock-level Label is
discarded after its Factor aggregate is calculated.
_Avoid_: Same-close return, implicit horizon, close-to-close default,
Alpha-recalculation input

### Strategy Results

**Strategy Backtest**:
The result that assesses the historical portfolio outcome produced by applying
a Strategy, next-open execution, costs, and adjusted valuation to Alpha Values.
It reports Gross and Net NAV from one actual fill path, with Net NAV as the
primary result.
_Avoid_: Factor Evaluation, Alpha, broker account statement

**Strategy Daily Observation**:
The retained minimal Strategy result for one Research Session. It records Gross
NAV, Net NAV, Benchmark NAV, Net Cash, session Transaction Costs, Actual
Holdings Count, Maximum Single-Name Weight, and the three Market Rejection
counts needed to derive the accepted report without duplicate Cash Ratio or
Drawdown series.
_Avoid_: Position history, target-weight history, order ledger, fill ledger

**Terminal Strategy State**:
The bounded ending account state required to seed or continue a DailyTrack:
all Terminal Positions with Execution Share Quantities and Adjusted Holding
Units, Net and Gross Cash and NAV, cumulative costs, Rebalance phase, and any
bounded pending execution signal. It is current account state rather than a
historical order, fill, target-weight, or per-position ledger.
_Avoid_: Strategy Daily Observation, Result Bundle history, broker account

**Gross NAV**:
Gross Cash plus every Actual Holding's Adjusted Holding Units multiplied by its
Adjusted Research Price, before Transaction Costs. It shares Net NAV's fill
path but is reporting-only and never changes Strategy decisions.
_Avoid_: Net NAV, independent Backtest, Target Portfolio value

**Net NAV**:
Net Cash plus every Actual Holding's Adjusted Holding Units multiplied by its
Adjusted Research Price, after all Transaction Costs. It is the only
decision-bearing accounting state and the only Strategy series compared with
the Strategy Benchmark.
_Avoid_: Gross NAV, pre-trade NAV, benchmark value

**Cumulative Return**:
The ending NAV divided by the common all-cash Initial Cash baseline, minus one.
V1 reports Gross and Net values separately, includes initial-deployment costs,
and uses Net Cumulative Return as the unlabeled primary Strategy result.
_Avoid_: Annualized Return, summed daily return, benchmark return

**Annualized Return**:
The compound annual growth rate of one NAV series using
`(ending / starting)^(252 / return_interval_count) - 1`. V1 reports Gross and
Net values separately and uses Net Annualized Return as the primary result.
_Avoid_: Arithmetic mean times 252, cumulative return, annualized volatility

**Net Excess NAV**:
Net NAV growth divided by Strategy Benchmark NAV growth from one common start.
It measures compounded relative wealth and is the only input to V1 Annualized
Excess Return.
_Avoid_: Gross excess, return subtraction, active-return sum

**Annualized Excess Return**:
The 252-market-session CAGR of Net Excess NAV. It is not the arithmetic
difference between Strategy and Benchmark Annualized Return.
_Avoid_: Annualized Return difference, Gross NAV comparison, daily alpha

**Maximum Drawdown**:
The largest value of `1 - Net NAV / running_peak_Net_NAV` over the reported
Research Period. V1 reports the non-negative loss magnitude plus its peak,
trough, and recovery dates; an unfinished recovery is `unrecovered`.
_Avoid_: Gross drawdown, negative signed value, single-day loss

**Annualized Volatility**:
The sample standard deviation of consecutive post-trade open Daily Net Returns,
using `ddof=1`, multiplied by `sqrt(252)`. Genuine zero-return intervals remain
in the series.
_Avoid_: NAV-level volatility, Gross volatility, population standard deviation

**Sharpe Ratio**:
The arithmetic mean Daily Net Return divided by its sample standard deviation,
then multiplied by `sqrt(252)`. V1 fixes the risk-free rate at zero and returns
no value when the denominator is zero or fewer than two intervals exist.
_Avoid_: CAGR divided by volatility, Gross Sharpe, external risk-free series

**Calmar Ratio**:
Net Annualized Return divided by the non-negative Maximum Drawdown. A negative
Net CAGR produces a negative ratio, while zero or unavailable drawdown produces
no value.
_Avoid_: Gross Calmar, Sharpe Ratio, infinite zero-drawdown result

**Open NAV Cycle**:
The V1 daily accounting order: value prior Adjusted Holding Units at the current
Adjusted Research Price, record pre-trade Gross and Net NAV, use only Net state
for Strategy decisions, execute scheduled integer Execution Share orders under
Raw Market Price constraints, transfer synthetic Research Settlement, deduct
Transaction Costs, and record post-trade Gross and Net NAV. Daily Strategy
return connects consecutive post-trade open NAV observations.
_Avoid_: Close NAV, pre-trade return series, intraday marking

**Backtest Start Baseline**:
The all-cash observation at the first Research Period open: Gross NAV and Net
NAV are Initial Cash, Benchmark NAV is 1, and Actual Holdings are empty. The
first close supplies the first signal and the next Open the first deployment.
_Avoid_: Warm-up position, pre-cost starting NAV, first holding return

**Terminal Valuation**:
The final Research Period open, when V1 values carried Actual Holdings and
records the final Strategy Daily Observation and Terminal Strategy State
without a Rebalance, forced liquidation, or hypothetical exit costs. It ends a
finite ResearchRun while an active DailyTrack continues beyond it.
_Avoid_: Final Rebalance, forced liquidation, post-window valuation

**Strategy Benchmark**:
The comparison series that starts at NAV 1 and applies equal-weight daily
returns of the ResearchRun's fixed Liquidity Universe over the same next-open
holding intervals as the Strategy, remaining flat through the
initial-deployment open. It retains confirmed full-session-suspended members
with zero return and no weight redistribution, uses observed partial-suspension
returns, applies `-100%` only for locally evidenced terminal delisting after a
valid starting mark, and never substitutes an external index.
_Avoid_: Implicit benchmark, default CSI 300, unrelated market index

### Dataset and Market Data

**End-of-Day Research**:
Research over completed Shanghai or Shenzhen A-share market sessions using
daily-granularity inputs available after the session closes. It never consumes
intraday updates.
_Avoid_: Intraday research, real-time research, live trading

**Research Calendar**:
The ordered intersection of dates on which both SSE and SZSE are open according
to Tushare exchange calendars. Every V1 session-counted window, horizon,
Rebalance Interval, and annualization uses this non-configurable calendar.
_Avoid_: Natural-day calendar, one-exchange union, per-run calendar

**Research Session**:
One completed date in the Research Calendar. A date when only one supported
exchange is open does not form a V1 cross-market research observation.
_Avoid_: Calendar day, source row, intraday session

**Requested Research Dates**:
The required natural-date `start_date` and `end_date` saved in a Research
Definition and frozen by a ResearchRun. They form an inclusive range and need
not themselves be Research Sessions; a reversed range or one containing no
Research Session is invalid.
_Avoid_: Session indexes, inferred default dates, Calculation Warm-up

**Research Period**:
The ordered Research Sessions from the first through the last valid session
inside the Requested Research Dates. It may contain any positive number of
sessions and is the only period reported by Factor Evaluation and Strategy
Backtest; its final session is the Terminal Valuation boundary.
_Avoid_: Fixed 504-session window, complete market history, Calculation Warm-up

**Calculation Warm-up**:
The completed Research Sessions before a Research Period needed solely to
evaluate the Alpha Expression's Effective Alpha Lookback. Its length is derived
from the expression, never exceeds 252 sessions, and contributes no signal,
order, Factor observation, or Strategy result. If the selected Data Generation
cannot supply it, the Attempt fails without shifting Requested Research Dates.
_Avoid_: Fixed 252-session prefix, Research Period, partial rolling calculation

**Mounted Canonical Data Store**:
The persistent directory that contains validated Canonical Market Data and the
current Dataset Head. Runtime startup reads this store and never downloads data;
an empty development store must be bootstrapped explicitly, while a deployment
may mount a previously prepared store.
_Avoid_: Runtime cache, Result Bundle store, startup download

**Dataset Head**:
The atomic pointer to the one current validated Data Generation. It is the data
source selected when a ResearchRun Attempt or Tracking Advance Attempt starts,
not an immutable user-visible version history.
_Avoid_: Dataset Release chain, ResearchRun result, permanent snapshot catalog

**Data Generation**:
A complete validated consistency boundary created beside the active data and
then selected by the Dataset Head. An active execution pins one Generation for
its duration and records its identity for audit, but old Generations and their
market-data bytes may be collected after no execution references them.
_Avoid_: Permanent Dataset Release, user-selectable version, Result Bundle

**Dataset Coverage**:
The inclusive range from the earliest Research Session through the
data-through session available in the current Dataset Head. Advancing the Head
does not reset its Coverage Start.
_Avoid_: Requested Research Dates, Calculation Warm-up, source request window

**Data Overview**:
The read-only user product view of current Dataset Coverage, data-through
session, last refresh time, and readiness. It contains no update control,
Generation history, or operator job status.
_Avoid_: Data Refresh control, operations console, Dataset Release browser

**Data Operator**:
The trusted operational authority that may inspect and start a Data Refresh
through the private operations surface. It is not an ordinary product user or
a Worker service identity.
_Avoid_: Ordinary user, research owner, Worker identity

**Data Refresh**:
The private, manually triggered operator action that builds and validates a
candidate Data Generation before atomically moving the Dataset Head. It is not
exposed through the ordinary user API or Web interface and has no automatic V1
schedule. A later refresh requests a 20-Research-Session overlap plus every new
session. Returned values replace matching values, and ordinary absence in the
overlap preserves current data. Explicit governing trading-state or lifecycle
evidence takes precedence and invalidates any conflicting stored price or
turnover observation.
_Avoid_: User product action, in-place partial mutation, automatic scheduler

**Dataset Bootstrap**:
The explicit operator initialization of an empty Mounted Canonical Data Store.
The current development default fetches the latest one natural year; that
operational default is not a ResearchRun length rule, and normal service startup
never repeats it.
_Avoid_: Automatic startup download, fixed research history, Data Refresh retry

**Canonical Market Data**:
The source-neutral fields and time semantics produced from validated upstream
responses and held in the Mounted Canonical Data Store, using stable system
names, types, and normalized units rather than Tushare's transport
representation. Research Definitions depend on this contract rather than
vendor field names or transport.
_Avoid_: Tushare response, vendor schema, runtime API data

**Canonical EOD Price**:
The `equity.eod_price` Dataset Family keyed by Instrument Identity and Research
Session. V1 maps all eleven long-history Tushare `daily` fields into normalized
raw prices, reference close, price change, return ratio, share volume, and CNY
turnover amount, then joins the separate Source Adjustment Factor and derives
fixed-anchor Adjusted Research Prices.
_Avoid_: Tushare daily response, qfq table, user-selected field subset

**Raw Market Price**:
The unadjusted nominal OHLC price in CNY for one instrument and market session,
whose daily `open` is the first traded session price and may occur after 09:30.
It supplies execution-price conditions and real-market execution constraints.
_Avoid_: Adjusted Research Price, qfq price, hfq price

**Adjusted Research Price**:
A corporate-action-continuous, per-instrument price coordinate derived from Raw
Market Price and Source Adjustment Factor using the fixed Adjustment Anchor
held in the selected Data Generation. The anchor has an Adjustment Scale of `1`
and never moves with the requested Research Period; price-based Alphas and
returns use this coordinate.
_Avoid_: Raw Market Price, CNY quote, dynamic qfq, hfq history

**Adjustment Anchor**:
The per-instrument record of `instrument_id`, `anchor_session`, and
`anchor_adjustment_factor` held in Canonical Market Data, using the first
post-listing session with both a valid raw daily bar and Source Adjustment
Factor. It may predate Calculation Warm-up and belongs to neither Strategy nor
the requested Research Period.
_Avoid_: Rolling-window base date, Strategy parameter, import timestamp

**Source Adjustment Factor**:
The positive, finite, dimensionless decimal `adj_factor` value accepted from
Tushare in the dated `equity.adjustment_factor` Dataset Family and used as an
input to Adjustment Scale rather than as an adjusted market price. Its valid
same-session presence is required for every daily bar accepted by Data Refresh.
_Avoid_: Adjustment Scale, adjusted price

**Adjustment Scale**:
The positive, finite, dimensionless decimal ratio of a session's Source
Adjustment Factor to that at one fixed anchor session. Multiplying Raw Market
Price by this scale produces Adjusted Research Price; the anchor scale is `1`.
_Avoid_: Source Adjustment Factor, dynamic qfq scale, rolling-window anchor

**Tushare Upstream**:
The sole external data source for every Dataset Family supported by
ThesisTrace. Data Refresh does not blend, reconcile, or fall back to another
provider; unavailable or invalid required Tushare inputs prevent the candidate
Generation from becoming the Dataset Head.
_Avoid_: Multi-provider abstraction, fallback source, cross-source consensus

**Field Catalog**:
The Data-owned inventory of stable Canonical Market Data fields and their
meaning, type, unit, availability semantics, and current Head presence. Research
authoring exposes only its Alpha-authorable subset together with the supported
Alpha Operator Set.
_Avoid_: Dataset Schema selector, source documentation, physical table browser

**Field Definition**:
The immutable meaning of one stable `field_id`, including its type, unit,
primary-key grain, and information-availability semantics. Adding a field
creates a new Dataset Schema version, correcting values preserves the definition
in a later Data Generation, and changing meaning requires a new `field_id`.
_Avoid_: Mutable field meaning, source column name, corrected data value

**Field Reference**:
One stable `field_id` selected from the Alpha-authorable Canonical Market Data
subset and displayed through its short Field Catalog name. A Research
Definition's Alpha Expression stores the stable reference directly.
_Avoid_: Vendor field name, manually typed identifier, compiled plan

**Dataset Schema**:
The internal, versioned contract for one Dataset Family's keys and fields. A
Data Generation records its exact version; a user does not select it
separately.
_Avoid_: Field Catalog, Dataset Head, Research Definition parameter

**Physical Data Object**:
An immutable-while-referenced data partition identified by its exact bytes
under the recorded writer contract. Data Generations may reuse unchanged
objects, and garbage collection may remove an object after no active Generation
or execution references it.
_Avoid_: Data Generation, mutable partial file, permanent historical promise

**Dataset Family**:
A versioned Canonical Market Data contract whose fields share an asset
boundary, primary-key grain, and information-availability semantics. Fields
with the same boundary may extend one family; data with a different grain,
availability timeline, or asset lifecycle belongs to another family.
_Avoid_: Source API, one universal wide table, storage partition

**Instrument Identity**:
The minimal shared identity referenced by all Dataset Families:
`instrument_id`, asset type, exchange, symbol, lifecycle, and Tushare code, with
the deterministic readable ID `{asset_type}:{ts_code}` rather than a random
UUID. V1 instantiates it only for ordinary CNY-denominated A-shares on the SSE
Main Board, SZSE Main Board, ChiNext, and STAR Market, while future asset
families reuse the identity without adding asset-specific attributes.
_Avoid_: Random UUID, surrogate-ID mapping table, asset-specific contract terms,
general provider registry

**Point-in-Time Financial Data**:
The future non-V1 `equity.financial_pit` Dataset Family, separate from
`equity.eod_price` and keyed by availability time so research sees only facts
available by each session, with date-only disclosures becoming available on the
next market session. It retains Tushare-provided versions and their availability
times within Canonical Market Data and marks revision coverage incomplete when
Tushare lacks the required history.
_Avoid_: Current financial snapshot, future backfill, invented revision history,
OHLCV extension

**Source Financial Version**:
One financial row or version actually returned by Tushare, retaining its source
announcement, report type, update marker, and observed values. ThesisTrace
preserves and maps source-provided versions but does not synthesize a company
revision chain that the source does not provide.
_Avoid_: Invented revision, destructive local overwrite, complete-PIT claim

**V1 Dataset Scope**:
The implemented ordinary-A-share end-of-day data families: instrument
reference, market calendar, raw OHLCV and turnover amount, Source Adjustment
Factors, Adjusted Research Prices, trading status, Liquidity Universe
membership, and historical SW2021 industry classification. Financial data,
futures, options, and convertible bonds are documented extension boundaries
and are not ingested or exposed in V1.
_Avoid_: Financial-data implementation, non-equity asset ingestion, intraday data

### Universe and Industry

**Universe Base Pool**:
The point-in-time ordinary-A-share membership snapshot that Data Refresh
produces for an `as_of_date` before liquidity ranking, covering the SSE Main
Board, SZSE Main Board, ChiNext, and STAR Market while excluding B-shares,
Chinese depositary receipts, Beijing Stock Exchange securities, funds, bonds,
preferred shares, and other non-ordinary equities. It preserves former-period
membership without current-status backfill, ignores ST and `*ST`, and derives
unambiguous membership from accepted Tushare `stock_basic`, dated `bak_basic`,
`daily`, and `suspend_d` evidence rather than interpreting lifecycle intervals
inside the Liquidity Universe.
_Avoid_: Current-listed-only stock list, Research Eligibility, all Tushare
instruments

**Liquidity Universe**:
A versioned rule that ranks instruments in the Universe Base Pool by their mean
daily turnover amount over the trailing 20 completed market sessions and
selects the top 300, 1000, 2000, or 3000 active instruments with sufficient
history, ordering mean descending and exact ties by `instrument_id` ascending.
Only Dataset Bootstrap Expansion permits a shorter window. Membership is
recalculated after each market session closes, while ST, suspension, and
price-limit policies remain downstream research or execution constraints.
_Avoid_: Static stock list, index constituents, research eligibility filter,
tradability filter

**Liquidity Rank**:
The unique one-based position of an instrument in one `as_of_date` liquidity
ordering, sorted by trailing-20-session mean `turnover_amount_cny` descending
and exact ties by `instrument_id` ascending. Top 300, 1000, 2000, and 3000
memberships are cut from this same ordering and are therefore deterministically
nested.
_Avoid_: Shared rank, source-response order, independent Top-N sorts

**Liquidity Observation Window**:
The target 20 completed market sessions ending on a Universe snapshot's
`as_of_date`. A confirmed full-session suspension contributes zero turnover, a
partial suspension contributes its observed amount, an unexplained missing
observation remains invalid, and an instrument listed after Dataset Coverage
Start cannot rank until it has all 20 governed observations.
_Avoid_: Last 20 non-missing observations, silent zero fill, new-listing expansion

**Dataset Bootstrap Expansion**:
The sole liquidity-window exception during the first nineteen sessions of the
entire Dataset Coverage. An instrument already listed at Coverage Start uses
the one through nineteen Dataset sessions then available; from the twentieth
Dataset session onward every instrument requires the full Liquidity Observation
Window. Data Refresh and later listings never restart expansion.
_Avoid_: New-listing grace period, rolling partial window, refresh reset

**Universe Membership**:
The ranked instruments produced by one Liquidity Universe for one
`as_of_date`, using market data available through that session's close. It is a
daily snapshot carrying the Canonical liquidity score and unique Liquidity
Rank, not an effective-date interval.
_Avoid_: Universe definition, permanent member list, effective-date range

**Research Eligibility**:
The downstream decision about which Universe Membership instruments may enter
Factor Evaluation or a Strategy's new-buy candidate set on one signal session.
V1 excludes instruments carrying their historically effective ST or `*ST`
designation without removing them from Universe Membership.
_Avoid_: Liquidity Universe ranking, permanent stock exclusion, current status
backfill

**Industry Classification**:
The SW2021 L1, L2, and L3 industries assigned to an instrument for a historical
market session, retained in Canonical Market Data as versioned
`[valid_from, valid_to_exclusive)` intervals with exactly one path per
instrument-date and no gap backfill. Research never applies current
classification to history, and V1 Industry Neutralization always uses L1.
_Avoid_: Current-industry field, Liquidity Universe, industry quota

**Industry Neutralization**:
The Research Definition option that emits either unchanged scores for `none` or
one same-Run score set demeaned by each instrument's historical SW2021 L1
industry after point-in-time ST exclusion for `industry`. Missing historical
classification and groups with fewer than two valid instruments are excluded
before the Final Alpha Cross-Section rather than assigned `UNKNOWN`, backfilled,
or emitted as a second result branch.
_Avoid_: Separate run type, automatic neutralization, two result branches
