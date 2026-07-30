# ThesisTrace

ThesisTrace turns investment hypotheses into reproducible Alpha evaluations,
strategy backtests, and continuous daily research tracking.

## Language

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
The Operator deploys and migrates services, issues Registration Invitations,
applies Quota Profile overrides, manages secrets and backups, performs disaster
recovery, and reviews platform-wide health. Operator authority is an
administrative deployment boundary and does not make the Operator the owner of
a User's Personal Workspace or research resources.
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

**Request Rate Limit**:
A short-window abuse and overload control applied to HTTP requests. Cloudflare
applies coarse unauthenticated limits by public route and client IP, while the
ThesisTrace API applies authenticated limits by User and Personal Workspace. It
does not allocate stored capacity or durable Compute work and is not a Quota
Profile dimension.
_Avoid_: Quota Profile, Compute concurrency, Personal Workspace storage limit

**Resource Exhaustion Failure**:
The terminal execution classification `RESOURCE_EXHAUSTED`, recorded after an
accepted Compute or Publication Activity exceeds its container resource
envelope twice. It identifies platform capacity or implementation failure, not
a User quota violation, disk-pressure admission rejection, validation error, or
unsuccessful investment result.
_Avoid_: QUOTA_EXCEEDED, retryable infrastructure event, Alpha failure

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

**System Health**:
The operational truth of whether the hosted services can safely accept,
schedule, execute, persist, and serve work. It covers Auth, API, PostgreSQL,
object storage, Temporal, workers, Dataset Publication, Activity heartbeats and
timeouts, Task Queues, and capacity pressure. Host CPU and memory are evidence,
not the whole definition.
_Avoid_: Host monitoring alone, Data Health, Quantitative Semantic Health

**Service Liveness**:
The cheap, dependency-independent evidence that one process is alive and able
to make internal progress. It never writes a Storage probe or declares
PostgreSQL, Temporal, Tushare, or telemetry healthy.
_Avoid_: Service Readiness, System Health, dependency check

**Service Readiness**:
The evidence that one service instance and its required internal dependencies
can safely receive that service's traffic or work. Optional external telemetry
and Tushare availability do not determine whole-platform Readiness.
_Avoid_: Service Liveness, Data Health, automatic restart signal

**Temporal Workflow Execution**:
The infrastructure execution coordinator linked to one finite Dataset
Publication, ResearchRun, Tracking Advance, equivalence-verification, or
maintenance-only Tracking Generation rebuild operation. It carries only opaque
resource identities, hashes, and small orchestration state; PostgreSQL remains
the product-state authority and bulk data remains in object storage.
_Avoid_: ResearchRun, domain truth, Alpha Matrix, permanent DailyTrack

**Compute Priority**:
The dispatch tier attached to a normal Compute Activity on the shared Temporal
Task Queue. P1 is reserved for automatic Tracking Advances, while P3 covers
ResearchRuns and explicit equivalence verification. Priority is evaluated
before equal-weight Personal Workspace fairness and never preempts a running
Activity.
_Avoid_: Quota Profile, Compute concurrency, Dataset Publication priority

**Data Health**:
The quality and timeliness of the path from Tushare inputs to an immutable
Dataset Release. It covers freshness, expected coverage, schema validity,
calendar consistency, duplicates, unexplained gaps, lineage, checksums, and
publication delay.
_Avoid_: Successful HTTP request, System Health, Alpha performance

**Quantitative Semantic Health**:
The evidence that research computation continues to honor its frozen domain,
numeric, and reproducibility contracts across Alpha Matrix, Factor Evaluation,
Strategy Backtest, and Daily Tracking. It includes deterministic regression
evidence, coverage and missing-reason behavior, accounting invariants,
canonical checksums, and Batch-Incremental Equivalence. It does not promise
that an Alpha remains profitable. Historical-correction boundaries and
release-sequence equivalence are separate visible evidence.
_Avoid_: Investment-performance guarantee, System Health, Data Health

**Investment Hypothesis**:
A human-readable claim about a market relationship that motivates an Alpha.
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
The bounded numeric formula embedded in a Research Definition. V1 permits
Canonical Market Data Field References, numeric literals, parentheses,
arithmetic, and a closed set of built-in functions; it does not permit Python,
SQL, arbitrary code, or user-defined functions. It is validated and evaluated
without creating a separate compiled domain artifact.
_Avoid_: Research DSL, Python strategy, SQL query, compiled plan

**V1 Alpha Function Set**:
The closed Alpha Expression operation set: arithmetic; `abs`, `log`, and
`sign`; `lag`, `delta`, and `pct_change`; and `ts_mean`, `ts_sum`, `ts_std`,
`ts_min`, and `ts_max`. Every time-series or rolling `n` must be an integer
literal from 1 through 252. Industry Neutralization is applied after expression
evaluation. V1 has no conditional, regression, correlation, or cross-sectional
functions.
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
The versioned V1 numeric boundary pinned by a frozen Research Definition and
DailyTrack. Exact integer quantities remain integers; Strategy decision and
accounting arithmetic uses the fixed 34-digit, half-even
`accounting_decimal_v1` context without cent quantization; and declared
binary64 outputs use IEEE 754. Canonical checksums encode normalized integer and
decimal values and binary64 bytes rather than UI-formatted numbers. V1 records
the supported contract automatically at Definition freeze; the user does not
configure it. Finite decimal division may create a deterministic last-digit
execution-rounding residual; V1 does not add a balancing account or classify
that residual as Transaction Cost.
_Avoid_: Runtime default precision, report formatting, tolerance-based equality

**Effective Alpha Lookback**:
The farthest market-session distance required by an Alpha Expression after
accounting for nested lag and rolling functions. V1 permits at most 252 market
sessions. A rolling length `n` includes `t-n+1` through `t`, whereas lag `n`
addresses `t-n`; validation composes those offsets through nested functions.
Missing observations do not extend the window, and a definition over the limit
cannot be frozen.
_Avoid_: Largest individual function argument, last valid observations,
automatic data-range expansion

**Missing Alpha Value**:
The absence of a usable Alpha score caused by missing formula inputs, an
incomplete rolling window, division by zero, an invalid logarithm, NaN, or
infinity under Alpha Numeric Semantics. V1 does not fill or skip such inputs.
A complete `ts_std(x,1)` validly returns zero. The instrument is excluded before
that session's Final Alpha Cross-Section and the coverage loss is reported.
_Avoid_: Zero Alpha Value, forward-filled score, partial-window result

**Alpha Values**:
The single set of instrument-by-session scores emitted by a ResearchRun. An
Alpha Value for session `t` is produced after that session closes from data and
Universe Membership available through `t`. A frozen Research Definition
selects either no neutralization or industry neutralization. The selected
option determines the scores produced by that run; it does not create a second
run type or parallel result branch. V1 does not automatically winsorize,
clip, rank-transform, or standardize the scores. The same completed Final Alpha
Cross-Section feeds Strategy Backtest, every Factor Evaluation horizon, and
Daily Tracking.
_Avoid_: Alpha, factor definition, trading signal

**Alpha Matrix**:
The deterministic instrument-by-Research-Session collection of Final Alpha
Values produced from one research-logic version and Dataset Release. Factor
Evaluation, Strategy Backtest, and Daily Tracking consume this same result;
none independently recalculates a differently transformed Alpha.
_Avoid_: Raw expression output, Strategy signal table, vendor factor table

**Daily Tracking**:
The V1 process that incrementally advances an explicitly active DailyTrack
after each successful Dataset Release. It appends the new Final Alpha
Cross-Section, matures Labels, and advances the simulated Strategy's orders,
holdings, cash, costs, and NAV. It does not send notifications or execute real
trades.
_Avoid_: Live trading, alerting product, mutable latest-only dashboard

**DailyTrack**:
The stable identity of one continuous, fixed-inception Daily Tracking stream
explicitly started from a successful seed ResearchRun. It pins the seed
Definition semantics, numeric contract, and Tracking Origin; its Activation
Dataset Release is exactly the seed Run's Release, and each Tracking Advance
separately binds one later Dataset Release. It is `active` from creation until
an operator terminally marks it `stopped`; a stopped Track retains its Head but
does not advance or resume in V1. Editing or rerunning research never mutates
an existing DailyTrack.
_Avoid_: ResearchRun, rolling backtest, mutable latest Definition

**Tracking Origin**:
The seed ResearchRun's original `R1` Research Session coordinate, all-cash
baseline, Research Window schedule anchor, and frozen Definition semantics from
which the DailyTrack reference oracle begins. Market data is resolved through
the ordered Dataset Release sequence bound by the Activation Checkpoint and
later Tracking Checkpoints, not frozen into the Origin or replaced
retroactively by the Head Release. It never rolls forward with the latest
504-session Research Window.
_Avoid_: Activation date only, latest rolling R1, Tracking Head

**Activation Checkpoint**:
Generation 0's root immutable DailyTrack state. It has no predecessor, binds
the seed Run's Dataset Release, references the seed Result Bundle, and carries
its terminal holdings, units, cash, NAV, Benchmark, costs, Rebalance phase,
pending Labels, and any scheduled final-session signal whose execution Research
Session is later than that Release.
_Avoid_: New all-cash baseline, copied Result Bundle, historical fake Update

**Tracking Advance**:
One idempotent execution for a `(DailyTrack, Tracking Generation, target
Dataset Release)`. It remains pending or blocked across failed execution
Attempts and becomes terminal only on success. It processes every new Research
Session in order and publishes one Tracking Checkpoint only on complete
success.
_Avoid_: ResearchRun rerun, Dataset Publication, partial result

**Tracking Advance Attempt**:
One execution attempt under a persistent Tracking Advance, with
`queued -> running -> succeeded | failed | cancelled`. A failed or cancelled
Attempt may be followed by another Attempt under the same Advance identity.
_Avoid_: New Tracking Advance, ResearchRun Attempt, partial Checkpoint

**Tracking Checkpoint**:
The immutable authoritative manifest and state published by a successful
Tracking Advance. It binds its Generation, same-Generation predecessor or null
Generation root, target release, processed sessions, new Alpha and Label
artifacts, Strategy events and state, versions, and checksums. Its predecessor
chain and each target release form the authoritative ordered Release sequence;
it identifies a Tracking Correction Boundary when applicable. A mutable
Tracking Head only points to one Checkpoint.
_Avoid_: Mutable tracker row, attempt log, Result Bundle extension

**Tracking Head**:
The mutable lookup pointer to the latest successful Tracking Checkpoint and
Generation for one DailyTrack. Moving the pointer atomically changes the
current view but never edits any Checkpoint or observation.
_Avoid_: Result truth, mutable Checkpoint, Dataset latest

**Tracking Generation**:
One immutable DailyTrack result branch. Normal Advances append within a
Generation, including an Advance whose Dataset Release contains an accepted
historical correction. Each Generation pins one calculation-kernel semantic
version under the DailyTrack's Numeric Execution Contract and has exactly one
predecessor-free root Checkpoint. A result-changing runtime fix requires a new
fully executed Generation. The prior as-known Generation remains queryable and
unchanged.
_Avoid_: Dataset correction boundary, partial patch, Dataset Release

**Tracking Correction Boundary**:
A successful Tracking Advance whose target Dataset Release contains an
accepted historical correction that affects the DailyTrack's dependency
closure. It continues from the prior Checkpoint in the same Generation,
preserves every previously published observation and account state, and uses
the corrected Release only for results first published by this and later
Advances. It is visible provenance, not a replay or historical rewrite.
_Avoid_: New Tracking Generation, corrected backtest, in-place mutation

**Batch-Incremental Equivalence**:
The core V1 correctness invariant that a reference execution and
session-by-session Daily Tracking from the same Tracking Origin, research
semantics, ordered Advance Dataset Release sequence, Generation-pinned
calculation kernel, and DailyTrack-pinned Numeric Execution Contract produce
canonically exact Alpha Values, matured Labels, orders, costs, holdings, cash,
NAV, and derived results. After a Tracking Correction Boundary, a calculation
that applies only the latest corrected Release from the Origin is a
counterfactual, not the comparator.
_Avoid_: Latest-Release-only replay, tolerance-only comparison, latest rolling Run

**Strategy**:
Rules that translate Alpha Values into portfolio targets and changes over time.
V1 has one type, `long_only_top_n_equal_weight`, which selects the highest
eligible Alpha Values using the Strategy Candidate Order, targets equal weights,
and leaves unallocated capital as cash without shorting or leverage.
_Avoid_: Alpha, factor, investment hypothesis

**Strategy Candidate Order**:
The deterministic total order `final_alpha DESC, instrument_id ASC` applied to
eligible target candidates at a scheduled Rebalance. V1 cuts the first
`holdings_count` targets from it and reuses it for buy-deficit priority after
sells. Its identity tie-break is Strategy-specific and never splits equal Alpha
Values across Factor quantiles.
_Avoid_: Database row order, source-response order, Factor average rank

**Holdings Count**:
The explicit `holdings_count` in a frozen V1 Research Definition. It is an
integer from 1 through 100, cannot exceed the selected Liquidity Universe size,
and defines the maximum number of Top-N equal-weight targets. A shortage of
eligible candidates produces fewer targets and residual cash.
_Avoid_: Runtime default, percentage cutoff, guaranteed filled positions

**Initial Cash**:
The CNY 10,000,000 recorded as both Gross NAV and Net NAV at the first Research
Window open, with no Actual Holdings. V1 fixes and explicitly records the
amount in the frozen Research Definition; first deployment occurs at the next
Research Session's open, and no later contribution, withdrawal, borrowing,
leverage, or negative cash is permitted.
_Avoid_: Runtime default, portfolio NAV, deployable cash after trades

**Rebalance**:
A scheduled Strategy decision that recalculates the complete Top-N equal-weight
target from that signal session's Alpha Values and first attempts the resulting
orders at the next session's open. Intermediate Alpha snapshots remain Factor
Evaluation inputs and are neither queued nor formed into overlapping Strategy
cohorts. A scheduled signal creates orders only if both its execution open and
one later holding-valuation open remain inside the Research Window.
_Avoid_: Delayed execution of every signal, daily signal cohort, Factor label

**Target Portfolio**:
The ideal equal-weight values calculated at a scheduled execution open by
dividing pre-trade Net NAV by the number of selected Top-N targets. V1 executes
eligible sells first and then buys target deficits in Strategy Candidate Order,
using Net Cash after each fill and its costs without allowing negative cash.
Execution constraints may make Actual Holdings differ from this target.
_Avoid_: Actual Holdings, guaranteed allocation, Factor quantile

**Actual Holdings**:
The positions and cash remaining after applying order eligibility, costs, and
rounding to a Target Portfolio. Each position has one integer Execution Share
Quantity for order rules and one Adjusted Holding Units balance for research
valuation. Strategy Backtest retains both actual and target weights rather than
presenting blocked or unaffordable orders as filled.
_Avoid_: Target Portfolio, pending order, ideal equal weight

**Execution Share Quantity**:
The non-negative integer quantity changed by filled Strategy orders. V1 uses it
for Board-Lot Rounding, Child Orders, Raw Market Price notional, and execution
constraints. It is an execution ledger coordinate, not a claim that V1
reconstructs broker shares through company actions.
_Avoid_: Adjusted Holding Units, broker share balance, market volume

**Adjusted Holding Units**:
The possibly fractional quantity used to value an Actual Holding as
`units * Adjusted Research Price`. A buy adds
`Execution Shares / Adjustment Scale`; a partial sell removes units in
proportion to the Execution Shares sold. The balance captures adjusted
total-return valuation without company-action events.
_Avoid_: Execution Share Quantity, Raw Market Price order quantity, stock split

**Research Settlement**:
The cash value transferred by a synthetic Strategy sale. It equals the
Adjusted Holding Units removed multiplied by current Adjusted Research Price;
Raw Market Price notional still controls order rules and Transaction Costs.
Research Settlement realizes adjusted total return and is not broker sale
proceeds.
_Avoid_: Raw notional, company-action event, broker cash settlement

**Actual Holdings Count**:
The number of instruments with positive Execution Share Quantity after each
open execution cycle. It excludes cash, includes retained off-target positions,
and may exceed Holdings Count. V1 retains the daily series plus mean, minimum,
maximum, and ending values.
_Avoid_: Holdings Count target, eligible candidate count, order count

**Maximum Single-Name Weight**:
The largest Actual Holding valuation divided by post-trade Net NAV on one open.
V1 retains the daily series and reports its period maximum, date, and ending
value without enforcing it as a Strategy position limit.
_Avoid_: Target equal weight, configured cap, largest order weight

**Cash Ratio**:
Post-trade Net Cash divided by Net NAV on one open. It is a deployment result,
not a target. V1 retains the daily series and reports its mean, period maximum
with date, and ending value.
_Avoid_: Cash target, unfilled ratio, Initial Cash

**Valuation Carry**:
The last valid Adjusted Research Price carried solely to mark a confirmed
full-session-suspended Actual Holding for Strategy NAV. It gives zero return
until a real post-suspension mark appears and is never exposed as Canonical
Market Data, Alpha input, Forward Return Label, or execution price. A partial
suspension with a valid daily bar never uses it.
_Avoid_: Forward fill, synthetic market bar, executable price

**Terminal Delisting Write-Off**:
The conservative Strategy accounting event applied only when an Actual Holding
has no required daily Open, is not governed by confirmed full-session
suspension, and has explicit effective terminal-delisting evidence in the
pinned Dataset Release. It removes the position at zero value and zero proceeds.
It creates no order, fill, Transaction Cost, Turnover, or Market Rejection, and
does not represent an observed zero-price trade.
_Avoid_: Forced sell, suspended-price carry, unexplained missing-data fallback

**Terminal Delisting Return**:
The synthetic `-100%` return produced only after a valid starting Adjusted
Research Price when explicit terminal delisting makes the required Benchmark
or Forward Return Label ending Open unavailable. A missing Label entry Open
cannot use this convention because it has no return base. Status resolution is
an on-demand local lookup, and zero is not a Canonical market price.
_Avoid_: Observed zero-price trade, suspension carry, missing-entry return

**Board-Lot Rounding**:
The conversion of a buy value deficit or proportional sell-value reduction into
a legal integer Execution Share Quantity. Buys use Raw Market Price; sells use
the current Execution Shares-to-adjusted-value proportion. Main-board and
ChiNext buys and partial sells use 100-share multiples; STAR Market buys require
at least 200 shares and then permit one-share increments. Complete liquidation
sells the entire remaining Execution Share Quantity, including an odd-lot
remainder. Below-minimum orders are omitted.
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
sides, and 0.0005 stamp duty on sells. Regulatory and exchange handling fees
are included in the all-in commission and are not deducted separately. The
cost base is Execution Share Quantity multiplied by Raw Market Price even when
a sell's synthetic Research Settlement differs. V1 uses decimal arithmetic
without per-order or per-Child-Order rounding to CNY 0.01; two-decimal report
formatting never changes accounting state.
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
The explicit `rebalance_every_sessions` integer in a frozen V1 Research
Definition. It may be any value from 1 through 20 and determines the distance
between scheduled Strategy signal sessions.
_Avoid_: Natural-day interval, fixed 1/5/20 enumeration, holding cohort

**Open Execution Model**:
The V1 rule that attempts a Strategy order at the next session's Raw Market
Price open, meaning that instrument's first traded daily price rather than a
fixed 09:30 timestamp. Only full-session suspension blocks both sides; an
upper-limit open blocks a buy and a lower-limit open blocks a sell. Every other
eligible order, including one after a partial opening suspension, fills
completely at the open without queue, partial-fill, capacity, impact, or
slippage simulation. Unknown or invalid open data fails Publication or
ResearchRun rather than blocking an order. This is a synthetic Backtest fill
assumption, not an exchange-native market-at-open order.
_Avoid_: Adjusted execution price, intraday fill model, guaranteed limit fill

**Blocked Order**:
A Strategy order that cannot execute at its one scheduled open under the Open
Execution Model. V1 cancels it without retry or candidate substitution: a
blocked buy leaves cash, while a blocked sell leaves the position unchanged.
Only a later scheduled Rebalance may create a new order.
_Avoid_: Pending order, partial fill, next-ranked replacement

**Market Rejection**:
One created logical order blocked by `upper_limit_buy`, `lower_limit_sell`, or
confirmed `full_session_suspended` with no daily open. V1 reports
reason-specific counts and event details, aggregating Child Orders and
calculating no unfilled ratio.
_Avoid_: Insufficient cash, below-board-lot omission, data-quality error

**Trading State**:
The one Canonical `equity.trading_state` value for an active instrument and
Research Session: `normal`, `open_suspended_partial`,
`after_open_suspended`, or `full_session_suspended`.
Both partial states retain a first traded daily Open. Only
`full_session_suspended` is a Market Rejection input, permits an absent daily
bar, and uses Valuation Carry.
_Avoid_: Missing-data fallback, pending order state, inferred zero turnover

**Held Missing-Open Resolution**:
The conditional local lookup path entered only for an Actual Holding without a
required daily Open. It checks Canonical full-session suspension first,
terminal-delisting evidence second, and otherwise reports unexplained data
loss. A valid daily Open bypasses the path, and ResearchRun never calls Tushare
per instrument.
_Avoid_: Daily delisting scan, remote runtime lookup, missing-price zero fill

**Execution Diagnostic**:
A recorded reason why a target or order was not created, such as insufficient
cash, a below-minimum Board Lot, insufficient candidates, or ineligibility. It
is distinct from a Market Rejection and from an unexplained-data failure.
_Avoid_: Blocked Order, successful fill, silent omission

**Existing-Position Eligibility**:
The scheduled reassessment of whether a current holding remains in Universe
Membership, has a valid final Alpha Value, is not ST or `*ST`, and remains in
the Top-N target set. Failure gives it a zero target at that Rebalance but never
causes an unscheduled liquidation.
_Avoid_: New-buy eligibility, immediate forced sale, permanent eligibility

**Research Definition**:
A versioned structured document that completely describes one research,
including its Investment Hypothesis, data, universe, period, Alpha, evaluation
rules, Strategy, execution, and costs. The editor maintains a mutable Draft.
Requesting Run validates it, resolves its concrete Dataset Release and field
bindings, and creates an immutable frozen version consumed directly by the new
ResearchRun. There is no separate user-visible Freeze action.
_Avoid_: ResearchSpec, Research DSL, Compiled Research Plan, mutable run settings

**Research Definition Draft**:
The mutable authoring revision in the V1 editor. A Run request either fails
validation and leaves it editable or creates a separate immutable frozen
Research Definition version. Editing later cannot modify a prior Run's frozen
input.
_Avoid_: Frozen definition, ResearchRun, compiled plan

**ResearchRun**:
One execution of a frozen Research Definition pinned to one Dataset Release
that produces separate Factor Evaluation and Strategy Backtest conclusions. It
cannot mix a calendar, Universe, Canonical field object, Adjustment Anchor, or
Adjustment Factor from another release. Its persistent lifecycle is
`queued -> running -> succeeded | failed | cancelled`. Transient infrastructure
retries are attempts under the same Run; a user rerun creates a new Run, and
idempotent creation prevents duplicate Runs from one repeated request. A
standard Run remains one rolling 756-input/504-report snapshot; a successful
Run may explicitly seed a separate continuous DailyTrack.
_Avoid_: Research Definition, factor evaluation, backtest

**ResearchRun Attempt**:
One infrastructure execution attempt belonging to an existing ResearchRun.
Retrying a transient failure may create another Attempt without changing the
Run identity or its frozen inputs. A user-requested rerun is a new ResearchRun,
not another Attempt.
_Avoid_: ResearchRun, user rerun, modified run input

**Result Bundle**:
The immutable structured and authoritative result of one successful
ResearchRun. Its Result Manifest binds the frozen Research Definition and
content hash, Dataset Release, research-semantics version, Numeric Execution
Contract, calculation-kernel semantic version, runtime build identity, and
checksummed Factor Evaluation, Strategy Backtest, time-series, event, and
diagnostic objects. UI and reports are derived views. The Run succeeds only
after the complete bundle is atomically published. A DailyTrack Activation
Checkpoint may reference the bundle but never extends or mutates it.
_Avoid_: UI cache, partial report, mutable result, attempt diagnostics

**Result Manifest**:
The immutable index and provenance record at the root of a Result Bundle. It
identifies every required result object and checksum so the bundle can be
validated and reproduced.
_Avoid_: Dataset Release manifest, HTML report, job log

**Factor Evaluation**:
The result that assesses whether an Alpha has predictive and ranking value
independently of a Strategy's realized portfolio outcome. V1 evaluates the same
Alpha Values at fixed 1-, 5-, and 20-market-session horizons.
_Avoid_: Strategy Backtest, factor return

**Label Maturation**:
An immutable Daily Tracking event that resolves one pending signal-session and
horizon Label when its nominal exit Research Session reaches `t+1+h`, whether
the governed result is a return, `-100%` terminal loss, or unavailable. It
records its Generation, effective maturity session, originating Alpha,
basis Dataset Release, and publishing Checkpoint; it appends current knowledge
without editing the seed Result Bundle or an earlier Checkpoint.
_Avoid_: In-place Label update, signal-date rewrite, latest-only value

**Factor Summary Snapshot**:
The immutable per-horizon Factor summary published by one Tracking Checkpoint
over the latest 504 signal sessions using observations mature and valid at that
Checkpoint. Older observations remain stored after leaving the current summary
window.
_Avoid_: Growing lifetime aggregate, mutable ResearchRun report, daily IC

**Rank IC**:
The daily cross-sectional standard Spearman correlation between valid final
Alpha Values and one Forward Return Label horizon. Exact ties receive their
average ascending rank and are never broken by instrument identity or row
order. A constant Alpha or label array produces no Rank IC. It is V1's primary
Factor Evaluation metric and is aggregated across sessions without pooling
stock-day rows.
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
also have a valid Forward Return Label for one horizon. Label availability is
filtered independently per horizon and never changes the Final Alpha
Cross-Section. V1 requires at least 30 and non-constant Alpha and label
cross-sections to calculate that session's IC and Rank IC; otherwise the metric
is missing as sample-insufficient.
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
Values in Q1 to highest in Q5. Equal Alpha Values receive a common average rank
`r` and enter `ceil(5 * r / N)` for sample size `N`. They therefore remain in
one group, so group sizes may differ or a group may be empty. V1 performs no
balancing pass. V1 requires at least 30 valid Alpha-and-label pairs for the
complete session-horizon quantile result; otherwise it is missing. It is a
Factor diagnostic, not a portfolio NAV.
_Avoid_: Sorting by future return, Strategy holding, cumulative backtest return

**Top-Bottom Return**:
The Factor diagnostic `Q5 return - Q1 return` for one signal session and
Forward Return Label horizon. It measures separation between high- and
low-Alpha groups without asserting that Q1 can be shorted or applying Strategy
costs.
_Avoid_: Executable long-short portfolio, Strategy excess return, net return

**Forward Return Label**:
The Adjusted Research Price return paired with an Alpha Value for session `t`.
For a horizon of `h` market sessions, it starts at the `t+1` open and ends at
the `t+1+h` open. V1 Factor Evaluation always produces the 1-, 5-, and
20-session labels. The label is attributed to signal session `t` but becomes
resolvable only when the nominal exit Research Session `t+1+h` enters the
Dataset Release. An observation without both required Opens has no ordinary
return Label for that horizon, subject only to the governed terminal-delisting
zero below.
Missing label availability excludes the instrument only from that horizon's
Effective Factor Sample; it does not change the Final Alpha Cross-Section.
V1 records `right_censored_by_release_end` or
`confirmed_market_open_unavailable` for expected unavailability; an
`unexplained_missing_or_invalid_data` condition fails Publication or
ResearchRun rather than becoming ordinary coverage loss. With a 504-session
Research Window ending at the pinned release, each instrument has at most 502,
498, and 483 labeled signal sessions for the 1-, 5-, and 20-session horizons
before other coverage loss. A partial suspension with a valid daily bar
supplies its first traded `open`; only full-session suspension makes that
coordinate unavailable. After a valid entry Open, explicit terminal delisting
on or before the exit supplies a synthetic zero terminal value and a `-100%`
Label. Terminal delisting before the entry leaves the Label unavailable.
During Daily Tracking, its 1-, 5-, and 20-session horizons mature respectively
at Research Sessions `t+2`, `t+6`, and `t+21` and append Label Maturation
events even when the governed outcome is unavailable or terminal loss.
_Avoid_: Same-close return, implicit horizon, close-to-close default,
Alpha-recalculation input

**Strategy Backtest**:
The result that assesses the historical portfolio outcome produced by applying
a Strategy, execution assumptions, and costs to Alpha Values. V1 first attempts
orders from `Alpha[t]` at the next session's Raw Market Price open, accrues
holding performance between successive opens from Adjusted Research Price, and
uses dual-unit synthetic research settlement rather than reconstructing
company-action cash and share events. It reports Gross and Net NAV from one
actual fill path, with Net NAV as the primary result.
_Avoid_: Factor Evaluation, Alpha, broker account statement

**Gross NAV**:
Gross Cash plus every Actual Holding's Adjusted Holding Units multiplied by its
Adjusted Research Price, before Transaction Costs. It uses the same fill
quantities as Net NAV and isolates cost drag without rerunning a separate
cost-free Strategy that could choose different quantities. It is reporting-only
and never feeds a target, order, affordability decision, holding, or weight.
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
Research Window. V1 reports the non-negative loss magnitude plus its peak,
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
The all-cash observation at the first Research Window open: Gross NAV and Net
NAV are Initial Cash, Benchmark NAV is 1, and Actual Holdings are empty. The
first Research Window close supplies the first Strategy signal and the next
open supplies the first deployment. The intervening Net Return contains only
initial Transaction Costs; Gross and Benchmark returns are zero.
_Avoid_: Warm-up position, pre-cost starting NAV, first holding return

**Terminal Valuation**:
The final Research Window open, when V1 values carried Actual Holdings and
records ending NAV, cash, weights, and diagnostics without a Rebalance. The
Strategy does not use a signal that would execute at this open, because no
reported holding interval would follow, and it does not force liquidation or
deduct hypothetical exit costs. This is a finite ResearchRun boundary; an
active DailyTrack continues beyond it under its Activation Checkpoint.
_Avoid_: Final Rebalance, forced liquidation, post-window valuation

**Strategy Benchmark**:
The daily equal-weight return of the Liquidity Universe selected by the same
frozen Research Definition. It is the comparison series for a Strategy
Backtest, not an external index selected implicitly by the runtime. Universe
Membership produced after signal session `t` applies to the return from the
`t+1` open to the `t+2` open, matching the Strategy holding interval.
Benchmark NAV is 1 at the Backtest Start Baseline and remains flat through the
initial-deployment open; its first market return begins with the first Strategy
holding interval.
Confirmed suspended members remain in the equal-weight denominator with zero
return only for `full_session_suspended` until a valid Adjusted Research Price
reappears; their weight is not redistributed. A partial suspension with a valid
bar uses its observed return. After a valid starting mark, explicit terminal
delisting at a missing ending Open supplies a synthetic zero value and a
`-100%` member return. The lookup occurs only for a missing required Open and
uses local Dataset Release evidence.
_Avoid_: Implicit benchmark, default CSI 300, unrelated market index

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

**Research Window**:
The final 504 completed Research Sessions reported by V1 Factor Evaluation and
Strategy Backtest. The immediately preceding 252 completed Research Sessions are
calculation-only warm-up inputs and are not part of the reported interval.
Release-owned Adjustment Anchors may predate both periods without becoming
research observations. Warm-up inputs may complete the first Alpha Expression
but their Alpha Values never create Strategy orders. Its final session is the
Strategy Terminal Valuation; Factor Evaluation independently retains signal
sessions according to each Forward Return Label's availability. This fixed
window belongs to a standard ResearchRun; a DailyTrack keeps its original
Tracking Origin and continuous account state rather than rolling to a new R1.
_Avoid_: Complete market history, warm-up period, unbounded date range

**Research Input History**:
The exact 756 completed Research Sessions consumed by a V1 ResearchRun: 252
warm-up sessions followed by the 504-session Research Window.
_Avoid_: Research Window, complete market history, report period

**Dataset Release**:
A platform-owned, immutable manifest for one validated market-data snapshot,
available read-only to every Personal Workspace. It is a cumulative logical
snapshot from Dataset Bootstrap through its final Research Session and binds the
exact Research Calendar, Universe snapshots, Canonical Dataset Schemas and
immutable Physical Data Objects, Adjustment Anchors, Adjustment Factors, and
other required dated families. Its manifest records its direct predecessor,
appended session range, and accepted historical correction change-set with
affected logical keys or ranges. The physical encoding may remain a small
predecessor-linked delta rather than copying all history. The Bootstrap Release
is the chain root with no predecessor, the complete bootstrapped calendar as its
appended range, and an empty correction change-set; every later Release names
one predecessor. Factor Evaluation, Strategy Backtest, Alpha generation and
validation, collaboration, and reproduction resolve data through this one
snapshot. A ResearchRun pins one release, while each Tracking Advance separately
pins its target release without modifying the DailyTrack's seed Definition.
`latest` may select a release before freezing but is never itself a reproducible
identity.
_Avoid_: Workspace-owned dataset, mutable dataset, latest dataset, runtime cache

**Dataset Publication**:
The platform-operated post-close process attempted only when a newly completed
Research Session extends the latest release. Personal Workspaces may consume its
Dataset Releases but do not publish them. It makes a new Dataset Release
available after all required daily inputs, pending accepted historical
corrections, and quality checks succeed. A correction without a new Research
Session waits for the next normal attempt. V1 incrementally fetches the new
session and does not re-scan the complete three-year history for corrections
after every close. After consecutive failures, one successful release catches
up to the latest completed session without manufacturing intermediate releases.
Failure leaves the previous latest release unchanged. A committed release may
enqueue independent active DailyTrack Advances, but Publication never waits for
or rolls back because of their outcome.
_Avoid_: Data fetch, partial update, in-place dataset mutation,
correction-only release

**Dataset Bootstrap**:
The initial ingestion that fetches the complete three-year Research Input
History and every required earlier dependency before the first V1 Dataset
Release can be published. Later Dataset Publication is incremental and does not
repeat this full historical fetch merely to scan for corrections.
_Avoid_: Daily publication, correction scan, Dataset Release

**Canonical Market Data**:
The source-neutral fields and time semantics produced from validated upstream
responses and published through a Dataset Release. Canonical fields use stable
system names, types, and normalized units rather than Tushare's transport
representation. Research definitions never depend on a vendor's field names or
transport.
_Avoid_: Tushare response, vendor schema, runtime API data

**Canonical EOD Price**:
The `equity.eod_price` Dataset Family keyed by Instrument Identity and Research
Session. V1 maps all eleven long-history Tushare `daily` fields into normalized
raw prices, reference close, price change, return ratio, share volume, and CNY
turnover amount, then joins the separate Source Adjustment Factor and derives
fixed-anchor Adjusted Research Prices.
_Avoid_: Tushare daily response, qfq table, user-selected field subset

**Raw Market Price**:
The unadjusted nominal OHLC price in CNY for one instrument and market session.
Its daily `open` is the instrument's first traded price for the session and may
occur after 09:30. Raw Market Price is used by execution-price conditions and
real-market execution constraints.
_Avoid_: Adjusted Research Price, qfq price, hfq price

**Adjusted Research Price**:
A corporate-action-continuous, per-instrument price coordinate derived from Raw
Market Price and Source Adjustment Factor using the fixed Adjustment Anchor
bound by Dataset Release. The anchor has an Adjustment Scale of `1` and never
moves with the rolling Research Window; price-based Alphas and returns use this
coordinate.
_Avoid_: Raw Market Price, CNY quote, dynamic qfq, hfq history

**Adjustment Anchor**:
The immutable per-instrument record of `instrument_id`, `anchor_session`, and
`anchor_adjustment_factor` bound by Dataset Release. Its session is the first
post-listing session with both a valid raw daily bar and Source Adjustment
Factor. It may predate Research Input History and never belongs to Strategy or
Research Window.
_Avoid_: Rolling-window base date, Strategy parameter, import timestamp

**Source Adjustment Factor**:
The positive, finite, dimensionless decimal `adj_factor` value accepted from
Tushare in the dated `equity.adjustment_factor` Dataset Family. It is an input
to the Adjustment Scale, not itself an adjusted market price. A daily bar
without its valid same-session factor prevents Dataset Publication.
_Avoid_: Adjustment Scale, adjusted price

**Adjustment Scale**:
The positive, finite, dimensionless decimal ratio of a session's Source
Adjustment Factor to that at one fixed anchor session. Multiplying Raw Market
Price by this scale produces Adjusted Research Price; the anchor scale is `1`.
_Avoid_: Source Adjustment Factor, dynamic qfq scale, rolling-window anchor

**Tushare Upstream**:
The sole external data source for every Dataset Family supported by
ThesisTrace. Dataset Publication does not blend, reconcile, or fall back to
another provider; unavailable or invalid required Tushare inputs prevent
publication.
_Avoid_: Multi-provider abstraction, fallback source, cross-source consensus

**Field Catalog**:
The user-facing inventory of stable Canonical Market Data fields, including
their meaning, unit, frequency, availability semantics, coverage, and presence
in a selected Dataset Release. It is the complete standard field directory;
only the separately permitted subset supports Alpha completion and validation.
_Avoid_: Dataset Schema selector, source documentation, physical table browser

**Field Definition**:
The immutable meaning of one stable `field_id`, including its type, unit,
primary-key grain, and information-availability semantics. Adding a field
creates a new Dataset Schema version. Correcting values keeps the definition
and enters the next new-session Dataset Release; changing meaning requires a
new `field_id`.
_Avoid_: Mutable field meaning, source column name, corrected data value

**Field Reference**:
A short Alpha-authorable canonical name. V1 permits exactly `$open_adj`,
`$high_adj`, `$low_adj`, `$close_adj`, `$volume_shares`, and
`$turnover_amount_cny`. Field Catalog provides discovery and completion for
that subset while still listing non-authorable execution and provenance
fields. Validation records the resolved stable `field_id` inside the same
frozen Research Definition; it does not produce a separate compiled artifact.
_Avoid_: Vendor field name, manually authored long identifier, compiled plan

**Dataset Schema**:
The internal, versioned contract for one Dataset Family's keys and fields. A
Dataset Release binds its exact version; a user does not select it separately.
_Avoid_: Field Catalog, Dataset Release, Research Definition parameter

**Physical Data Object**:
An immutable partition or content-addressed object containing actual data.
Dataset Releases reuse existing objects and add only new or corrected objects,
rather than duplicating the complete historical dataset.
_Avoid_: Dataset Release, mutable latest table, full daily copy

**Dataset Family**:
A versioned Canonical Market Data contract whose fields share an asset
boundary, primary-key grain, and information-availability semantics. Fields
with the same boundary may extend one family; data with a different grain,
availability timeline, or asset lifecycle belongs to another family.
_Avoid_: Source API, one universal wide table, storage partition

**Instrument Identity**:
The minimal shared identity referenced by all Dataset Families:
`instrument_id`, asset type, exchange, symbol, lifecycle, and Tushare code.
`instrument_id` is the deterministic, readable `{asset_type}:{ts_code}`, not a
random UUID. V1 instantiates it only for ordinary CNY-denominated A-shares on
the SSE Main Board, SZSE Main Board, ChiNext, and STAR Market; future asset
families reuse the identity without placing their asset-specific attributes in
the common contract.
_Avoid_: Random UUID, surrogate-ID mapping table, asset-specific contract terms,
general provider registry

**Point-in-Time Financial Data**:
The future `equity.financial_pit` Dataset Family, not implemented in V1, keyed
and timestamped so a research session can use only financial facts available by
that session. It is separate from `equity.eod_price` rather than appended as
daily-bar columns. A disclosure with a precise publication time becomes
available according to that time; when only its publication date is known, it
becomes available on the next market session. Source-provided versions and
changed later pulls are retained without overwriting earlier Dataset Releases.
Revision coverage is reported as incomplete when Tushare does not expose the
required history.
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

**Universe Base Pool**:
The point-in-time ordinary-A-share membership snapshot that Dataset Publication
produces for an `as_of_date` before liquidity ranking. It covers the SSE Main
Board, SZSE Main Board, ChiNext, and STAR Market and excludes B-shares, Chinese
depositary receipts, Beijing Stock Exchange securities, funds, bonds including
convertible bonds, preferred shares, and other non-ordinary-equity instruments.
The Liquidity Universe consumes this snapshot and does not interpret listing
statuses or maintain listing-lifecycle intervals. A security that later delists
remains in snapshots from its former listed period; current listing status is
never backfilled into history. Dataset Publication builds the snapshot from
accepted Tushare `stock_basic`, dated `bak_basic`, `daily`, and `suspend_d`
evidence and fails if required membership remains ambiguous. ST and `*ST`
status does not alter this pool.
_Avoid_: Current-listed-only stock list, Research Eligibility, all Tushare
instruments

**Liquidity Universe**:
A versioned rule that ranks instruments in the Universe Base Pool by their mean
daily turnover amount over the trailing 20 completed market sessions and
selects the top 300, 1000, 2000, or 3000 instruments. The rule is fixed; its
membership is recalculated after each market session closes. Its ranking pool
contains instruments active on that date with sufficient history for the
liquidity measure. It sorts the mean descending and breaks an exact tie by
`instrument_id` ascending before applying the Top-N cutoff. ST policy,
suspension, and price-limit state are downstream research or execution
constraints and do not redefine the Universe.
_Avoid_: Static stock list, index constituents, research eligibility filter,
tradability filter

**Liquidity Rank**:
The unique one-based position of an instrument in one `as_of_date` liquidity
ordering. V1 sorts trailing-20-session mean `turnover_amount_cny` descending,
then `instrument_id` ascending only for exact score ties. Top 300, 1000, 2000,
and 3000 memberships are cut from this same total ordering, so they are
deterministically nested.
_Avoid_: Shared rank, source-response order, independent Top-N sorts

**Liquidity Observation Window**:
The 20 completed market sessions ending on a Universe snapshot's `as_of_date`.
A confirmed full-session suspension contributes zero turnover amount; a partial
suspension with a valid bar contributes its observed amount. An unexplained
missing observation remains invalid and is never converted to zero. An
instrument with fewer than 20 post-listing sessions is not ranked.
_Avoid_: Last 20 non-missing observations, silent zero fill, variable lookback

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
market session. Dataset Releases retain the classification version and
historical membership as `[valid_from, valid_to_exclusive)` intervals. Exactly
one path may cover an instrument-date; overlaps fail Dataset Publication and a
source gap remains Missing without extending or backfilling another interval.
Industry neutralization defaults to L1; a Research Definition may explicitly
select L2 or L3. Research must not apply today's industry classification to
past sessions.
_Avoid_: Current-industry field, Liquidity Universe, industry quota

**Industry Neutralization**:
An Alpha-processing option in a Research Definition. `none` emits the Alpha's
scores directly; `industry` emits industry-neutralized scores. Either choice is
executed by the same ResearchRun and produces one set of Alpha Values. The
`industry` option operates on valid Alpha Expression outputs remaining after
point-in-time ST exclusion and subtracts, for each market session, the
equal-weight mean of the instrument's selected industry from that instrument's
output. An instrument without a valid historical industry classification for
that session is excluded before the Final Alpha Cross-Section and reported as
missing coverage; it is not assigned to an `UNKNOWN` industry or backfilled
with its current classification. An industry group with fewer than two valid
instruments is excluded before demeaning and reported as insufficient.
_Avoid_: Separate run type, automatic neutralization, two result branches
