# ThesisTrace

ThesisTrace turns investment hypotheses into auditable Alpha evaluations,
strategy backtests, and continuous daily research tracking. This glossary names
the product's domain concepts; behavior and implementation decisions belong in
the [ADR index](docs/adr/README.md) and [Core architecture](docs/architecture/core.md).

## Language

### Identity and Access

**Operator**:
A Researcher who holds the Operator Capability and manages Researcher access
and Canonical Data through the Operator Console or private operational commands.
_Avoid_: Separate administrator identity, Organization administrator

**Operator Capability**:
The unique privileged grant held by exactly one Researcher and allowing that
Researcher to act as the Operator. It is indivisible and does not form a
general permission hierarchy.
_Avoid_: Role, RBAC, permission set, Organization membership

**Operator Assignment**:
The unique association between one active Researcher and the Operator
Capability, established or transferred only by a private deployment action.
_Avoid_: Role assignment, Console permission management, Organization membership

**Operator Proof**:
A short-lived, single-use current-password confirmation bound to one Login
Session and one exact Operator mutation.
_Avoid_: Login Session, confirmation window, API key, reusable bearer token

**Operator Console**:
The privileged product surface through which an Operator manages Researcher
access and Invitations, starts Data Refreshes, and reviews Dataset Operational Status.
_Avoid_: Admin dashboard, Settings, ordinary product navigation

**Researcher**:
An authenticated human who owns one private set of Research Folders,
ResearchRuns, Research Batches, and DailyTracks and may also hold the Operator
Capability without changing that Research Ownership.
_Avoid_: User, account, tenant, Personal Workspace

**Login Session**:
A revocable, time-bounded authentication grant that lets one client act as one
active Researcher.
_Avoid_: Research Session, ResearchRun, permanent access, API key

**Researcher Invitation**:
A single-use, expiring, email-bound grant issued by the Operator that allows one
person to create one Researcher.
_Avoid_: Public signup, shared invitation code, Organization invitation

**Research Ownership**:
The invariant that binds every private Research resource to exactly one
Researcher and excludes every other Researcher.
_Avoid_: Login Session, Folder membership, optional owner

**Researcher Deactivation**:
The reversible Operator action that revokes a Researcher's access without
cancelling accepted Research or stopping DailyTracks, while preserving their
Research Ownership and private Research resources.
_Avoid_: Researcher deletion, ResearchRun cancellation, DailyTrack Stop,
expired Login Session

### Research and Alpha

**Investment Hypothesis**:
An optional human-readable claim about a market relationship that motivates an
Alpha.
_Avoid_: Alpha, formula, Strategy

**Alpha Proposal**:
A non-authoritative structured Research Agent presentation of one prospective
Alpha Formula and its research configuration inside an Agent Chat Session.
_Avoid_: Alpha, Browser Draft, ResearchRun, Result Bundle

**Alpha**:
An executable scoring rule that produces one cross-sectional score per eligible
instrument and Research Session.
_Avoid_: Investment Hypothesis, Alpha Values, Strategy

**Alpha Direction**:
The convention that a higher Alpha Value always expresses a stronger
expectation of higher future return.
_Avoid_: Automatic reversal, absolute IC, inferred direction

**Alpha Language**:
The canonical language in which authors express executable Alpha Formulae.
_Avoid_: Alpha Formula, Alpha Expression, general-purpose Python

**Alpha Formula**:
The author-editable expression submitted by a Browser Draft and frozen by a
ResearchRun.
_Avoid_: Alpha Expression, Python program, Strategy

**Alpha Compiler**:
The authoritative validator that resolves an Alpha Formula and either returns
Alpha Diagnostics or produces a canonical Alpha Expression.
_Avoid_: Frontend validator, formula evaluator

**Alpha Expression**:
The canonical bounded expression tree compiled from an Alpha Formula and used
as a ResearchRun's Alpha execution truth.
_Avoid_: Alpha Formula, editable source, arbitrary code

**Composite Alpha**:
One Alpha Formula that explicitly combines multiple numeric inputs into one
Alpha Value per instrument and Research Session.
_Avoid_: Factor list, automatic weighting, model training

**Alpha Value Model**:
The small static type system that distinguishes Numeric Series, Number, and
literal Window values in the Alpha Language.
_Avoid_: Dynamic object model, physical storage type

**Alpha Operator Set**:
The closed platform-owned set of arithmetic, scalar, time-series, rolling, and
cross-sectional operations available to Alpha Formulas.
_Avoid_: User-defined function, Strategy rule

**Cross-Sectional Rank**:
The `rank(x)` Alpha operation that maps finite values to their relative position
within the selected Liquidity Universe for each Research Session.
_Avoid_: Time-series rank, whole-market rank, Industry Neutralization

**Alpha Authoring Catalog**:
The read-only catalog of Alpha-authorable Fields and operations used to validate
Alpha Formulae.
_Avoid_: Editable registry, physical data catalog

**Alpha Field Capability**:
The explicit declaration that a Canonical Field may be referenced by an Alpha
Identifier and resolved as a Numeric Series.
_Avoid_: All-numeric exposure, frontend allowlist

**Alpha Identifier**:
The globally unique lowercase `snake_case` name used for a Field or operation in
an Alpha Formula.
_Avoid_: Display label, namespaced Field Reference, legacy name

**Alpha Numeric Semantics**:
The fixed rules for numeric conversion, invalid values, rounding, and operator
meaning inside Alpha evaluation.
_Avoid_: Storage type, UI formatting, runtime default

**Numeric Execution Contract**:
The single current contract that makes ResearchRun and DailyTrack calculations
and serialized results deterministic.
_Avoid_: Report formatting, tolerance-based equality, version dispatcher

**Effective Alpha Lookback**:
The farthest preceding Research Session required to evaluate an Alpha
Expression after nested lag and rolling operations are combined.
_Avoid_: Largest individual Window, last valid observations

**Alpha Diagnostic**:
A structured finding that identifies an Alpha Formula problem and its exact
source range.
_Avoid_: Generic error string, frontend verdict

**Missing Alpha Value**:
The absence of a usable Alpha score because required input or calculation is
missing, invalid, or non-finite.
_Avoid_: Zero, imputed value, partial-window result

**Alpha Values**:
The deterministic instrument-by-session scores produced by an Alpha Expression
inside a ResearchRun or Tracking Advance.
_Avoid_: Alpha, Strategy signal, persisted factor table

### Research Lifecycle and Factor Evaluation

**Research Agent**:
An external actor that performs explicitly authorized Research and Daily Tracking
actions on behalf of a person using ThesisTrace. It does not own product
resources or receive Data Operator authority.
_Avoid_: Research Worker, Data Operator, autonomous trader, User account

**Research Agent Authority**:
The explicitly granted set of product actions a Research Agent may invoke.
Authority to admit or observe Research does not imply authority to cancel it or
irreversibly stop a DailyTrack.
_Avoid_: Human confirmation, Tool visibility, Data Operator authority

**Agent Chat Session**:
A durable conversation owned by one Researcher that may produce multiple
ResearchRuns without owning their inputs, lifecycle, or results.
_Avoid_: Login Session, Research Session, ResearchRun, authoritative Research record

**Research Folder**:
A durable, one-level container owned by one Researcher that organizes
ResearchRuns without owning their inputs or results.
_Avoid_: Research Definition, nested directory, Browser Draft

**Batch Research Folder**:
The per-Researcher system-created Research Folder for ResearchRuns admitted
through a Research Batch; Folder membership does not define Batch ownership.
_Avoid_: Research Batch, immutable membership, folder-name lookup

**Browser Draft**:
The browser-local, non-authoritative authoring state for one Researcher's
prospective Research in one Research Folder.
_Avoid_: ResearchRun, server Draft, latest Run

**Research Kind**:
The immutable choice between `factor_evaluation` and `strategy_backtest` for one
ResearchRun.
_Avoid_: Execution role, optional Strategy flag

**ResearchRun**:
The durable Research resource that freezes one submitted research question,
calculation contract, Research Kind, and Data Generation.
_Avoid_: Research Folder, Browser Draft, Result Bundle

**Research Batch**:
A durable Research resource that groups ordinary ResearchRuns sharing one
Research Folder, Research Period, Liquidity Universe, Industry Neutralization
choice, and Data Generation without owning their Result Bundles.
_Avoid_: Batch, Batch-Incremental Equivalence, bulk request receipt

**Research Batch Kind**:
The immutable choice between evaluating several Alphas independently and
scanning several Strategy parameter combinations for one shared Alpha.
_Avoid_: Research Kind, mixed Batch, inferred Batch type

**Research Batch Item**:
The immutable membership record that maps one submitted `item_key` to its
ResearchRun identity and final execution outcome, even if that terminal Run is
later deleted.
_Avoid_: ResearchRun, Result Bundle, Folder entry

**Research Batch State**:
The durable aggregate lifecycle of a Research Batch from admission through one
terminal execution or cancellation outcome.
_Avoid_: ResearchRun State, task heartbeat, inferred UI status

**Research Batch Cancellation**:
The explicit stop of one Research Batch's remaining work that preserves its
terminal record and already-published Results while discarding incomplete
calculation state.
_Avoid_: Research Deletion, Result rollback, individual Run cancellation

**Research Batch Progress**:
The user-visible combination of durably completed Batch tasks and estimated
work within the current incomplete task.
_Avoid_: Partial Result, recovery checkpoint, guaranteed completion time

**ResearchRun State**:
The durable user-visible lifecycle of a ResearchRun from admission through one
terminal outcome.
_Avoid_: Attempt heartbeat, UI-only status

**ResearchRun Progress**:
The monotonic durable measure of completed Research Period work; in-flight work
is never counted as complete.
_Avoid_: Partial Result, guaranteed finish time

**Research Name**:
The mutable, non-unique display name of one ResearchRun.
_Avoid_: Alpha name, ResearchRun identity, immutable input

**Research Deletion**:
The explicit permanent removal of one terminal ResearchRun without deleting a
DailyTrack that originated from it.
_Avoid_: Cancel, Folder deletion, cascading Track deletion

**Result Bundle**:
The immutable authoritative result of one successful ResearchRun, shaped by its
Research Kind.
_Avoid_: Alpha store, UI cache, partial report

**Factor Evaluation**:
The Research Period summary of an Alpha's predictive ranking and correlation
quality independently of a Strategy's portfolio outcome.
_Avoid_: Strategy Backtest, Factor curve, durable signal table

**Label Maturation**:
The point when a signal-session Forward Return Label becomes resolvable because
its exit Research Session is available.
_Avoid_: Stored Label row, signal-date rewrite

**Factor Summary Snapshot**:
The immutable bounded Factor summary published at one Tracking Checkpoint.
_Avoid_: Daily Factor history, mutable ResearchRun report

**Rank IC**:
The daily cross-sectional Spearman correlation between valid Final Alpha Values
and one Forward Return Label horizon.
_Avoid_: Pearson IC, time-series correlation, pooled correlation

**IC**:
The daily cross-sectional Pearson correlation between valid Final Alpha Values
and one Forward Return Label horizon.
_Avoid_: Rank IC, regression coefficient, pooled correlation

**ICIR**:
The mean of a valid daily IC or Rank IC series divided by its sample standard
deviation.
_Avoid_: Strategy information ratio, t-statistic

**Effective Factor Sample**:
The Final Alpha Cross-Section members that also have a valid Forward Return Label
for one horizon.
_Avoid_: Universe Membership, Strategy holdings, imputed sample

**Final Alpha Cross-Section**:
The one instrument-to-score set remaining for a signal session after Research
Eligibility and any selected Industry Neutralization are applied.
_Avoid_: Horizon-specific Alpha, raw expression output

**Five-Quantile Return**:
The equal-weight Forward Return of five daily groups ordered from the lowest to
highest Alpha Values.
_Avoid_: Strategy portfolio, cumulative backtest return

**Top-Bottom Return**:
The Q5 return minus Q1 return for one signal session and Forward Return Label
horizon.
_Avoid_: Executable long-short Strategy, Net Return

**Forward Return Label**:
The Adjusted Research Price return attributed to signal session `t`, measured
from the `t+1` Open to the horizon's exit Open.
_Avoid_: Same-close return, Alpha input, implicit horizon

### Daily Tracking

**Daily Tracking**:
The forward-only simulated-portfolio process that extends an explicitly active
DailyTrack through later Research Sessions. It may use degraded-but-executable
Financial Research Readiness and records that state without rewriting a
completed Tracking Advance after later data arrives.
_Avoid_: Rolling backtest, live trading, persisted Alpha history, rewritten past

**DailyTrack**:
The stable identity of one continuous fixed-origin tracking stream started from
a successful Strategy Backtest ResearchRun.
_Avoid_: ResearchRun, rolling backtest, Browser Draft

**DailyTrack Deletion**:
The explicit permanent removal of a stopped DailyTrack and its owned state.
_Avoid_: Stop, Research Deletion, automatic cascade

**DailyTrack Stop**:
The irreversible action that fences further Tracking publication and reaches
`stopped` only after active execution has ended.
_Avoid_: Pause, Retry, Delete

**Tracking Origin**:
The successful seed ResearchRun and Terminal Strategy State from which a
DailyTrack continues, including the first investable Entry Open and Initial
Cash that remain the Strategy Comparison baseline.
_Avoid_: Activation date, rolling ResearchRun, Tracking Head, rebased comparison

**Activation Checkpoint**:
The immutable root state of a DailyTrack, derived from its Tracking Origin.
_Avoid_: New all-cash baseline, copied Result Bundle

**Tracking Advance**:
One idempotent unit of work that extends a DailyTrack through a frozen Tracking
Advance Target and publishes at most one Tracking Checkpoint.
_Avoid_: ResearchRun, Data Refresh, partial result

**DailyTrack Refresh**:
The explicit Researcher command that queues one new Tracking Advance for an
active, lagging, idle DailyTrack.
_Avoid_: Data Refresh, page Reload, Dataset Head trigger, automatic Advance

**Tracking Advance Target**:
The fixed contiguous set of oldest unpublished Research Sessions assigned to one
Tracking Advance.
_Avoid_: Current backlog, mutable target

**Tracking Checkpoint**:
The immutable authoritative state published by a successful Tracking Advance.
_Avoid_: Mutable Track row, Attempt log, Result Bundle extension

**Tracking Head**:
The current pointer to a DailyTrack's latest successful Tracking Checkpoint.
_Avoid_: Mutable Checkpoint, Dataset Head

**Tracking Progress**:
The user-visible combination of authoritative Tracking Head, lag, and current
Advance liveness.
_Avoid_: Provisional Head, elapsed-time completion

**Batch-Incremental Equivalence**:
The invariant that batch Research and session-by-session Daily Tracking produce
canonically identical retained results from identical inputs and origin state.
_Avoid_: Tolerance-only comparison, latest rolling Run

### Strategy Execution

**Strategy**:
The rules that translate Alpha Values into portfolio targets and changes over
time.
_Avoid_: Alpha, Factor, Investment Hypothesis

**Strategy Candidate Order**:
The deterministic order used to select equal-weight targets and prioritize buy
deficits at a Rebalance.
_Avoid_: Source order, Factor quantile rank

**Holdings Count**:
The explicit maximum number of Top-N targets selected by a Strategy.
_Avoid_: Filled-position guarantee, percentage cutoff

**Initial Cash**:
The fixed all-cash Gross and Net NAV baseline from which a Strategy Backtest
starts.
_Avoid_: Current cash, deployable cash after costs

**Rebalance**:
A scheduled Strategy decision that replaces the complete Target Portfolio using
the signal session's Final Alpha Cross-Section.
_Avoid_: Every-session signal cohort, Factor Label

**Target Portfolio**:
The ideal equal-weight allocation selected at a Rebalance before execution
constraints are applied.
_Avoid_: Actual Holdings, guaranteed allocation

**Actual Holdings**:
The positions and cash that remain after order eligibility, costs, and quantity
rules are applied to a Target Portfolio.
_Avoid_: Target Portfolio, pending order

**Execution Share Quantity**:
The non-negative integer share coordinate used for Strategy orders and market
execution constraints.
_Avoid_: Adjusted Holding Units, broker share ledger

**Adjusted Holding Units**:
The possibly fractional quantity used with Adjusted Research Price to value an
Actual Holding through corporate actions.
_Avoid_: Execution Share Quantity, broker share balance

**Research Settlement**:
The synthetic cash value transferred when Adjusted Holding Units are removed by
a Strategy sale.
_Avoid_: Raw notional, broker settlement, company-action event

**Actual Holdings Count**:
The number of instruments with positive Execution Share Quantity after an open
execution cycle.
_Avoid_: Holdings Count, candidate count, order count

**Maximum Single-Name Weight**:
The largest Actual Holding value as a share of post-trade Net NAV.
_Avoid_: Target equal weight, configured cap

**Cash Ratio**:
Post-trade Net Cash divided by Net NAV.
_Avoid_: Cash target, Initial Cash

**Valuation Carry**:
The last valid Adjusted Research Price used only to value a confirmed
full-session-suspended Actual Holding.
_Avoid_: Forward fill, executable price, synthetic market bar

**Terminal Delisting Write-Off**:
The conservative zero-value removal of an Actual Holding when explicit terminal
delisting makes a required Open unavailable.
_Avoid_: Forced sale, suspension carry, missing-data fallback

**Terminal Delisting Return**:
The synthetic `-100%` return used when explicit terminal delisting makes a valid
Forward Return Label exit unavailable.
_Avoid_: Observed zero-price trade, missing-entry return

**Board-Lot Rounding**:
The conversion of an intended order value into an exchange-valid integer
Execution Share Quantity.
_Avoid_: Fractional share, universal lot rule

**Child Order**:
One exchange-limit-compliant piece of a larger logical Strategy order.
_Avoid_: Partial fill, replacement order

**Transaction Costs**:
The fixed deductions charged to filled Strategy orders under the current
research cost contract.
_Avoid_: Slippage, market impact, hidden fee

**Transaction Cost Return Drag**:
Gross Cumulative Return minus Net Cumulative Return from the same fill path.
_Avoid_: Annualized drag, relative return ratio

**Turnover**:
The half-sum of absolute same-open changes in actual instrument and cash weights.
_Avoid_: Order count, target-weight change

**Rebalance Interval**:
The number of Research Sessions between scheduled Strategy signal sessions.
_Avoid_: Natural-day interval, holding cohort

**Open Execution Model**:
The synthetic contract that attempts eligible Strategy orders at the next
Research Session's Raw Market Price Open.
_Avoid_: Intraday model, Adjusted execution price

**Blocked Order**:
A Strategy order that cannot execute at its single scheduled Open and is not
retried or substituted.
_Avoid_: Pending order, partial fill

**Market Rejection**:
A logical Strategy order blocked by a governed price-limit or full-session
suspension condition.
_Avoid_: Insufficient cash, invalid data, below-lot omission

**Trading State**:
The Canonical classification of an instrument's trading availability during one
Research Session.
_Avoid_: Missing-data fallback, pending-order state

**Held Missing-Open Resolution**:
The governed decision that distinguishes full-session suspension, terminal
delisting, and unexplained data loss for a held position without a required Open.
_Avoid_: Zero fill, remote runtime lookup

**Execution Diagnostic**:
A bounded reason why an intended target or order was not created, distinct from
a Market Rejection.
_Avoid_: Blocked Order, successful fill

**Existing-Position Eligibility**:
The scheduled reassessment of whether an Actual Holding remains eligible for the
new Target Portfolio.
_Avoid_: Immediate liquidation, permanent eligibility

### Strategy Results

**Strategy Backtest**:
The historical portfolio result produced by applying Strategy execution, costs,
and adjusted valuation to Alpha Values.
_Avoid_: Factor Evaluation, broker statement

**Strategy Daily Observation**:
The minimal retained Strategy result for one Research Session.
_Avoid_: Position history, order ledger, fill ledger

**Terminal Strategy State**:
The bounded ending portfolio state required to seed or continue a DailyTrack.
_Avoid_: Historical ledger, Strategy Daily Observation

**Gross NAV**:
Gross Cash plus the adjusted value of Actual Holdings before Transaction Costs.
_Avoid_: Net NAV, Target Portfolio value

**Net NAV**:
Net Cash plus the adjusted value of Actual Holdings after Transaction Costs.
_Avoid_: Gross NAV, pre-trade NAV

**Cumulative Return**:
Ending NAV divided by the common Initial Cash baseline, minus one.
_Avoid_: Annualized Return, summed daily return

**Annualized Return**:
The 252-Research-Session compound annual growth rate of a NAV series.
_Avoid_: Cumulative Return, Annualized Volatility

**Net Excess NAV**:
Net NAV growth divided by one plus Benchmark Relative Return from the same
investable baseline.
_Avoid_: Return subtraction, Gross excess

**Annualized Excess Return**:
The 252-Research-Session compound annual growth rate of Net Excess NAV.
_Avoid_: Difference of annualized returns

**Maximum Drawdown**:
The largest peak-to-trough loss magnitude in Net NAV over the Research Period.
_Avoid_: Gross drawdown, single-session loss

**Annualized Volatility**:
The annualized sample standard deviation of consecutive Daily Net Returns.
_Avoid_: NAV-level volatility, Gross volatility

**Sharpe Ratio**:
The annualized mean Daily Net Return divided by its sample standard deviation,
using the product's fixed zero risk-free rate.
_Avoid_: CAGR divided by volatility, Gross Sharpe

**Calmar Ratio**:
Net Annualized Return divided by Maximum Drawdown.
_Avoid_: Sharpe Ratio, infinite zero-drawdown result

**Open NAV Cycle**:
The daily Strategy accounting sequence from pre-trade valuation through open
execution to the post-trade NAV observation.
_Avoid_: Close NAV, intraday marking

**Backtest Start Baseline**:
The all-cash observation at the first Research Period Open before any Strategy
position exists.
_Avoid_: Warm-up position, first holding return

**Terminal Valuation**:
The final Research Period Open valuation recorded without another Rebalance or
forced liquidation.
_Avoid_: Final Rebalance, hypothetical exit

**Strategy Benchmark**:
The fixed CSI 300 Price Index used to compare Strategy performance over the same
Open-to-Open interval beginning at the first investable Entry Open.
_Avoid_: Selected-universe benchmark, configurable benchmark, total-return index

**Benchmark Level**:
The official CSI 300 Price Index Open point for one Research Session.
_Avoid_: Benchmark NAV, benchmark return, constituent average

**Benchmark Snapshot**:
The one current append-only sequence of Benchmark Levels used by every Strategy
Comparison.
_Avoid_: Dataset Family, Data Generation, per-ResearchRun copy, Benchmark history

**Benchmark Relative Return**:
The Benchmark Level divided by its level at the first investable Entry Open,
minus one.
_Avoid_: Benchmark NAV, daily pct_chg, return since 2010

**Strategy Comparison**:
The comparison that aligns immutable Strategy facts with the current Benchmark
Snapshot over one Entry-to-Terminal Open interval.
_Avoid_: Strategy Result, benchmark execution state, browser calculation

### Dataset and Market Data

**End-of-Day Research**:
Research over completed Shanghai and Shenzhen A-share Research Sessions using
daily-granularity information available after the session closes.
_Avoid_: Intraday research, real-time research, live trading

**Research Calendar**:
The ordered intersection of dates on which both the SSE and SZSE are open.
_Avoid_: Natural-day calendar, one-exchange union

**Research Session**:
One completed date in the Research Calendar.
_Avoid_: Calendar day, source row, intraday session

**Requested Research Dates**:
The inclusive natural-date range submitted by a Browser Draft and frozen by a
ResearchRun.
_Avoid_: Session indexes, inferred dates, Calculation Warm-up

**Research Period**:
The ordered Research Sessions inside Requested Research Dates and the sole
period reported by Factor Evaluation and Strategy Backtest.
_Avoid_: Complete history, Calculation Warm-up

**Calculation Warm-up**:
The Research Sessions before a Research Period required only to evaluate the
Alpha Expression's Effective Alpha Lookback.
_Avoid_: Research Period, reported results

**Dataset Head**:
The atomic pointer to the one current validated Data Generation.
_Avoid_: Dataset history, ResearchRun result

**Data Generation**:
A complete validated Canonical Data consistency boundary that may be frozen by
Research work while the Dataset Head advances.
_Avoid_: User-selectable release, Result Bundle

**Dataset Coverage**:
The verified extent declared by one Dataset Family inside a Data Generation.
_Avoid_: Requested Research Dates, universal date range

**Market Coverage**:
The Dataset Coverage of end-of-day market families through one completed
Research Session.
_Avoid_: Financial Coverage, Research Period

**Benchmark Coverage**:
The Research Session extent for which the current Benchmark Snapshot can support
Strategy Comparison.
_Avoid_: Dataset Coverage, Data Generation, lagging benchmark, carried level

**Financial Coverage**:
The quality-bearing Dataset Coverage of Point-in-Time Financial Data, including
its discovery baseline, attempted-through and complete-through coordinates,
pending instruments, discovery gaps, and reconciliation limits.
_Avoid_: One observation-through date, non-null guarantee, market date range

**Financial Coverage Start**:
The first Research Session from which the bootstrap financial family can resolve
covered Source Financial Versions under its declared revision limits.
_Avoid_: Financial Discovery Baseline, earliest retained row, source request start

**Financial Discovery Baseline**:
The observation-through Research Session of the last accepted complete-history
Tushare bootstrap or explicit reconciliation, after which announcement-driven
discovery continuity begins.
_Avoid_: Financial Coverage Start, historical CNINFO scan, hard-coded date

**Financial Seed Fact**:
A pre-Coverage Financial Fact retained only to resolve a correct
Session-Aligned Financial Field at Financial Coverage Start.
_Avoid_: Earlier Financial Coverage, invented value

**Data Overview**:
The read-only product view of current Dataset Coverage, Benchmark Snapshot
readiness and identity, freshness, Financial Research Readiness, and aggregate
pending or discovery-gap counts.
_Avoid_: Dataset Operational Status, Data Refresh control, raw table browser,
instrument failure dump

**Dataset Operational Status**:
The Operator view of the current Dataset Head and recent Data Refresh targets,
phases, outcomes, bounded counts, and safe failure codes.
_Avoid_: Data Overview, Dataset history, raw table browser, object-store browser

**Financial Research Readiness**:
The published financial input-quality status of a Data Generation: `ready`,
`ready_with_pending`, `ready_with_gaps`, or `not_ready`. The first three remain
executable and are frozen into ResearchRun and DailyTrack provenance;
`not_ready` blocks use.
_Avoid_: Boolean readiness, raw ingestion completion, hidden stale input

**Data Operator**:
The operational capability through which the Operator initializes, inspects,
refreshes, and collects Canonical Data.
_Avoid_: Researcher access management, ordinary Researcher action

**Dataset Bootstrap**:
The explicit Data Operator action that creates the first complete Data
Generation and Dataset Head for an empty data store.
_Avoid_: Automatic startup download, Data Refresh retry

**Data Refresh**:
The Operator action that builds a validated candidate Data Generation and
atomically advances the Dataset Head.
_Avoid_: User product action, in-place mutation

**Data Refresh Operation**:
The durable record of one explicit Market, Financial, or Industry Refresh
target accepted from the Operator and processed in submission order.
_Avoid_: HTTP request, combined Refresh, scheduled job

**Data Operator Worker**:
The single-slot runtime that serially claims and executes Data Refresh
Operations.
_Avoid_: Research Worker, scheduler, per-Refresh process

**Market Refresh**:
A Data Refresh that advances end-of-day market families while retaining the
current financial families.
_Avoid_: Financial Refresh, independent Dataset Head

**Financial Refresh**:
A Data Refresh that uses Financial Announcement Discovery to atomically
re-request all three Tushare statements only for affected instruments while
retaining prior facts for failed instruments and current market families.
_Avoid_: Full-universe daily rebuild, mixed per-instrument snapshot, fallback,
independent Dataset Head

**Financial Announcement Discovery**:
The immutable CNINFO evidence, obtained through the pinned AKShare adapter, that
produces Financial Announcement Triggers and Financial Discovery Gaps but no
Canonical financial values.
_Avoid_: Tushare statement collection, numeric data source, title-only guess

**Financial Discovery Attempted Through**:
The latest Research Session through which a Financial Refresh published either
complete announcement evidence or explicit discovery gaps.
_Avoid_: Financial Discovery Complete Through, implicit success

**Financial Discovery Complete Through**:
The latest Research Session through which every declared announcement category
and page has been observed without an unresolved Financial Discovery Gap.
_Avoid_: Financial Discovery Attempted Through, Tushare statement freshness

**Financial Discovery Gap**:
A persisted incomplete CNINFO category, page, and date interval whose affected
instruments remain unknown and which must be retried by a later refresh.
_Avoid_: Known instrument failure, discarded remote error, complete discovery

**Financial Announcement Trigger**:
A deduplicated current-instrument disclosure or correction that requires an
atomic three-statement Tushare refresh. It resolves for the stock when that
validated refresh changes Canonical financial facts or confirms none changed;
collection or projection failure leaves it unresolved.
_Avoid_: Canonical Financial Fact, exact announcement-version link,
five-refresh waiting item, best-effort log

**Canonical Market Data**:
The source-neutral market and reference facts governed by stable field names,
types, units, and availability semantics.
_Avoid_: Vendor response, transport schema

**Canonical EOD Price**:
The daily Canonical price family containing raw market observations, adjustment
facts, and derived Adjusted Research Prices.
_Avoid_: Tushare response, user-selected field subset

**Raw Market Price**:
The unadjusted nominal OHLC price quoted in CNY for one instrument and Research
Session.
_Avoid_: Adjusted Research Price, qfq price

**Adjusted Research Price**:
The corporate-action-continuous price coordinate used for Alpha and return
calculations rather than market execution.
_Avoid_: Raw Market Price, quoted execution price

**Source Adjustment Factor**:
The dated positive dimensionless adjustment fact supplied by Tushare for one
instrument and Research Session.
_Avoid_: Adjusted price, Strategy parameter

**Adjustment Scale**:
The same-session scale applied to Raw Market Price to produce Adjusted Research
Price.
_Avoid_: Latest-factor anchor, Raw Market Price

**Tushare Upstream**:
The sole external source of Canonical market, industry, and financial values.
CNINFO supplies financial discovery evidence only and never substitutes values.
_Avoid_: Sole evidence source, AKShare financial values, fallback, consensus

**Field Catalog**:
The Data-owned inventory of stable Canonical Fields and their research meaning.
_Avoid_: Source documentation, physical table browser

**Field Definition**:
The immutable meaning, grain, type, unit, availability, and capabilities of one
stable Field identity.
_Avoid_: Mutable meaning, source column name

**Field Reference**:
The stable namespaced identity of one Canonical Field stored in an Alpha
Expression.
_Avoid_: Alpha Identifier, display label, vendor field name

**Dataset Family**:
A Canonical Data contract whose Fields share an asset boundary, primary-key
grain, and information-availability semantics.
_Avoid_: Source API, storage partition, universal wide table

**Instrument Identity**:
The minimal stable identity shared by Dataset Families for one supported market
instrument.
_Avoid_: Random UUID, asset-specific data record

**Point-in-Time Financial Data**:
Financial facts keyed by source availability and first observation so research
never sees a later disclosure early and late ingestion never rewrites a
completed DailyTrack progression.
_Avoid_: Current snapshot, future leak, rewritten Tracking history

**Source Financial Version**:
One financial statement version actually returned by Tushare with its source
availability, first-observed time, and revision evidence.
_Avoid_: Invented revision, destructive overwrite, merged time coordinates

**Financial Fact**:
One nullable Canonical numeric measurement from a Source Financial Version with
its reporting and availability context.
_Avoid_: Filled zero, daily Alpha field

**Consolidated Reporting Scope**:
The reporting boundary that combines a listed parent and controlled subsidiaries
while preserving parent-owner attribution.
_Avoid_: Parent-only statement, mixed scope

**Session-Aligned Financial Field**:
A Canonical financial field that resolves to at most one value per Instrument
Identity and Research Session under fixed point-in-time semantics.
_Avoid_: Raw statement column, implicit latest report

**Latest Annual Financial Field**:
A Session-Aligned Financial Field that selects the latest available full-year
Financial Fact.
_Avoid_: TTM field, latest interim report

**Latest Reported Stock Field**:
A Session-Aligned Financial Field that selects the latest available
balance-sheet Financial Fact regardless of report period.
_Avoid_: Annual-only stock, period average

**Financial Field Applicability**:
The explicit company-type set for which a Session-Aligned Financial Field has a
comparable meaning.
_Avoid_: Hidden company filter, zero fill

**Dataset Scope**:
The current ordinary-A-share end-of-day market, reference, industry, and
Point-in-Time Financial Data needed by Alpha research, Factor Evaluation,
Strategy Backtest, and Daily Tracking.
_Avoid_: Intraday data, non-equity assets, live trading data

### Universe and Industry

**Universe Base Pool**:
The point-in-time set of ordinary SSE and SZSE A-shares eligible for liquidity
ranking before research-specific filters are applied.
_Avoid_: Current-listed-only list, Research Eligibility

**Liquidity Universe**:
A daily ranked selection from the Universe Base Pool based on trailing completed
session turnover amount.
_Avoid_: Static stock list, index constituents, tradability filter

**Liquidity Rank**:
The unique deterministic position of one instrument in a daily Liquidity
Universe ordering.
_Avoid_: Source order, independent Top-N rank

**Liquidity Observation Window**:
The governed completed-session history used to calculate one instrument's
Liquidity Rank.
_Avoid_: Last non-missing observations, silent zero fill

**Universe Membership**:
The ranked instruments selected by one Liquidity Universe for one Research
Session.
_Avoid_: Universe definition, permanent member list

**Research Eligibility**:
The downstream decision about which Universe Membership instruments may enter a
signal session's Alpha, Factor, and new-buy calculations.
_Avoid_: Liquidity ranking, permanent exclusion

**Industry Classification**:
The single point-in-time primary SW2021 industry path assigned to an instrument
for a Research Session; raw source memberships do not qualify until they resolve
to one path.
_Avoid_: Raw index membership, current-industry backfill, Liquidity Universe

**Industry Neutralization**:
The optional cross-sectional demeaning of Alpha Values within each instrument's
point-in-time SW2021 L1 industry.
_Avoid_: Separate Research Kind, automatic neutralization
