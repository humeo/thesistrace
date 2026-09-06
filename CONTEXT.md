# ThesisTrace Domain Glossary

## Identity and Access

**Operator**:
The Researcher entrusted with managing Researcher access and the shared Canonical Data used for research.
_避免混用_: Research Ownership, ordinary Researcher access

**Operator Capability**:
The indivisible authority assigned to one active Researcher to act as the Operator.
_避免混用_: Research Ownership, a second administrator identity

**Operator Proof**:
The Researcher's fresh confirmation authorizing one exact Operator action within one Login Session.
_避免混用_: Login Session, permission for a different action

**Researcher**:
An authenticated human who owns one private set of Research Folders,
ResearchRuns, Research Batches, and DailyTracks and may also hold the Operator
Capability without changing that Research Ownership.
_避免混用_: User, account, tenant, Personal Workspace

**Login Session**:
A revocable, time-bounded grant allowing one person to act as an active Researcher.
_避免混用_: Agent Chat Session, Research Session, ResearchRun

**Researcher Invitation**:
A single-use, expiring, email-bound grant issued by the Operator that allows one
person to create one Researcher.
_避免混用_: Public signup, shared invitation code, Organization invitation

**Research Ownership**:
The invariant that binds every private Research resource to exactly one
Researcher and excludes every other Researcher.
_避免混用_: Login Session, Folder membership, optional owner

**Researcher Deactivation**:
The reversible Operator action that revokes a Researcher's access without
cancelling accepted Research or stopping DailyTracks, while preserving their
Research Ownership and private Research resources.
_避免混用_: Researcher deletion, ResearchRun cancellation, DailyTrack Stop,
expired Login Session

## Research and Alpha

**Investment Hypothesis**:
An optional human-readable claim about a market relationship that motivates an
Alpha.
_避免混用_: Alpha, formula, Strategy

**Alpha Proposal**:
A non-authoritative structured Research Agent presentation of one prospective
Alpha Formula and its research configuration inside an Agent Chat Session.
_避免混用_: Alpha, Browser Draft, ResearchRun, Result Bundle

**Alpha**:
An executable scoring rule that produces one cross-sectional score per eligible
instrument and Research Session.
_避免混用_: Investment Hypothesis, Alpha Values, Strategy

**Alpha Direction**:
The convention that a higher Alpha Value always expresses a stronger
expectation of higher future return.
_避免混用_: Automatic reversal, absolute IC, inferred direction

**Alpha Language**:
The notation available to researchers for expressing Alpha Formulae using approved fields and mathematical operations.
_避免混用_: Alpha Formula, investment narrative

**Alpha Formula**:
The author-written scoring expression in the Alpha Language, whose accepted meaning is fixed for a ResearchRun.
_避免混用_: Investment Hypothesis, Alpha Values, Strategy

**Composite Alpha**:
One Alpha Formula that explicitly combines multiple numeric inputs into one
Alpha Value per instrument and Research Session.
_避免混用_: Factor list, automatic weighting, model training

**Alpha Operator Set**:
The available arithmetic, time-series, rolling, and cross-sectional operations in the Alpha Language.
_避免混用_: Strategy rules, financial data fields

**Cross-Sectional Rank**:
The `rank(x)` Alpha operation that maps finite values to their relative position
among members of the selected Liquidity Universe that pass Research Eligibility for each Research Session.
_避免混用_: Time-series rank, whole-market rank, Industry Neutralization

**Alpha Authoring Catalog**:
The supported research fields and mathematical operations available when writing an Alpha Formula.
_避免混用_: All reported financial facts, a submitted Alpha

**Alpha Identifier**:
The unambiguous authoring name for a field or mathematical operation in an Alpha Formula.
_避免混用_: Display label, source statement column

**Effective Alpha Lookback**:
The farthest preceding Research Session required to evaluate an Alpha
Formula after nested lag and rolling operations are combined.
_避免混用_: Largest individual Window, last valid observations

**Alpha Diagnostic**:
A finding identifying a problem in an Alpha Formula and the part of the formula responsible.
_避免混用_: A poor investment result, missing source data

**Missing Alpha Value**:
The absence of a usable Alpha score because required input or calculation is
missing, invalid, or non-finite.
_避免混用_: Zero, imputed value, partial-window result

**Alpha Values**:
The instrument-by-session scores produced by an Alpha Formula for the eligible research population.
_避免混用_: Alpha Formula, Target Portfolio, realized returns

## Research Lifecycle and Factor Evaluation

**Research Agent**:
An assistant that performs authorized Research and Daily Tracking actions on behalf of a Researcher, without owning the resulting research.
_避免混用_: Researcher, Operator, autonomous trader

**Research Agent Authority**:
The set of research actions a Researcher permits an assistant to perform on their behalf. Permission to create or inspect research does not imply permission to cancel research or stop tracking.
_避免混用_: Research Ownership, confirmation of a particular action

**Agent Chat Session**:
A Researcher-owned conversation that may propose or refer to multiple ResearchRuns while remaining independent of their lifecycles and results.
_避免混用_: Login Session, Research Session, ResearchRun

**Agent Chat Memory**:
The still-relevant facts, constraints, and decisions retained within one Agent Chat Session.
_避免混用_: Cross-conversation recall, current execution status, authoritative Research results

**Agent Chat Summary**:
The account of the current task's goal, progress, blockers, and next steps used to continue work within one Agent Chat Session.
_避免混用_: Agent Chat Memory, Result Bundle, completed research without authoritative evidence

**Research Folder**:
A one-level Researcher-owned grouping of ResearchRuns that organizes research without changing its accepted inputs or results.
_避免混用_: Research Batch, Alpha definition

**Batch Research Folder**:
The per-Researcher system-created Research Folder for ResearchRuns admitted
through a Research Batch; Folder membership does not define Batch ownership.
_避免混用_: Research Batch, immutable membership, a folder with the same name

**Browser Draft**:
An unsubmitted, editable research proposal belonging to one Researcher and one Research Folder.
_避免混用_: Accepted ResearchRun, Alpha Proposal

**Research Kind**:
The choice of Factor Evaluation or Strategy Backtest fixed for one ResearchRun.
_避免混用_: Research Batch Kind, execution progress

**ResearchRun**:
One accepted research question with fixed Alpha, Research Kind, Research Period, and Data Generation, followed through completion, failure, or cancellation.
_避免混用_: Research Folder, Browser Draft, Result Bundle

**Research Batch**:
An ordered group of ResearchRuns sharing one Research Period, Liquidity Universe, Industry Neutralization choice, and Data Generation, admitted together and managed as one research request. Each item remains a separate ResearchRun with its own result.
_避免混用_: Research Folder, one combined Result Bundle, Batch-Incremental Equivalence

**Research Batch Kind**:
The immutable choice between evaluating several Alphas independently and
scanning several Strategy parameter combinations for one shared Alpha.
_避免混用_: Research Kind, mixed Batch, inferred Batch type

**Research Batch Item**:
The association between one submitted batch item and its ResearchRun and execution outcome, preserved even when the completed ResearchRun is deleted.
_避免混用_: Result Bundle, mutable Folder membership

**Research Batch Cancellation**:
The explicit stop of a Research Batch’s unfinished work while preserving completed items and their Results.
_避免混用_: Research Deletion, Result rollback, individual Run cancellation

**Research Batch Progress**:
The completed portion of a Research Batch and the estimated work within its current incomplete item.
_避免混用_: Published Result, guaranteed completion time

**ResearchRun Progress**:
The completed Research Sessions within a ResearchRun, excluding work whose outcome is still unfinished.
_避免混用_: Partial Result, guaranteed completion time

**Research Name**:
The mutable, non-unique display name of one ResearchRun.
_避免混用_: Alpha name, ResearchRun identity, immutable input

**Research Deletion**:
The explicit permanent removal of one terminal ResearchRun without deleting a
DailyTrack that originated from it.
_避免混用_: Cancel, Folder deletion, cascading Track deletion

**Result Bundle**:
The fixed, authoritative result of one successful ResearchRun, containing the findings appropriate to its Research Kind.
_避免混用_: Alpha Formula, provisional calculation, Research Batch

**Factor Evaluation**:
The Research Period summary of an Alpha's predictive ranking and correlation
quality independently of a Strategy's portfolio outcome.
_避免混用_: Strategy Backtest, Factor curve, Alpha Values

**Label Maturation**:
The point when a signal-session Forward Return Label becomes resolvable because
its exit Research Session is available.
_避免混用_: Stored Label row, signal-date rewrite

**Rank IC**:
The daily cross-sectional Spearman correlation between valid Final Alpha Values
and one Forward Return Label horizon.
_避免混用_: Pearson IC, time-series correlation, pooled correlation

**IC**:
The daily cross-sectional Pearson correlation between valid Final Alpha Values
and one Forward Return Label horizon.
_避免混用_: Rank IC, regression coefficient, pooled correlation

**ICIR**:
The mean of a valid daily IC or Rank IC series divided by its sample standard
deviation.
_避免混用_: Strategy information ratio, t-statistic

**Effective Factor Sample**:
The Final Alpha Cross-Section members that also have a valid Forward Return Label
for one horizon.
_避免混用_: Universe Membership, Strategy holdings, imputed sample

**Final Alpha Cross-Section**:
The one instrument-to-score set remaining for a signal session after Research
Eligibility and any selected Industry Neutralization are applied.
_避免混用_: Horizon-specific Alpha, raw expression output

**Five-Quantile Return**:
The equal-weight Forward Return of five daily groups ordered from the lowest to
highest Alpha Values.
_避免混用_: Strategy portfolio, cumulative backtest return

**Top-Bottom Return**:
The Q5 return minus Q1 return for one signal session and Forward Return Label
horizon.
_避免混用_: Executable long-short Strategy, Net Return

**Forward Return Label**:
The Adjusted Research Price return attributed to signal session `t`, measured
from the `t+1` Open to the horizon's exit Open.
_避免混用_: Same-close return, Alpha input, implicit horizon

## Daily Tracking

**Daily Tracking**:
The forward-only simulated-portfolio process that extends a DailyTrack through later Research Sessions after an explicit DailyTrack Refresh. Later data arrivals do not rewrite completed tracking.
_避免混用_: Automatic updates, rolling backtest, live trading

**DailyTrack**:
A continuous simulated portfolio started from one successful Strategy Backtest, retaining that fixed Tracking Origin throughout its active, blocked, or stopped lifetime.
_避免混用_: ResearchRun, rolling backtest, live account

**DailyTrack Deletion**:
The explicit permanent removal of a stopped DailyTrack and its owned state.
_避免混用_: Stop, Research Deletion, automatic cascade

**DailyTrack Stop**:
The irreversible end of a DailyTrack, complete only when its active advance has ended and no further tracking result can be added.
_避免混用_: Pause, DailyTrack Deletion, retry

**Tracking Origin**:
The successful seed ResearchRun and its ending portfolio and performance state from which a DailyTrack continues. Its first investable Entry Open and Initial Cash remain the comparison baseline.
_避免混用_: Activation date, a new all-cash portfolio, rolling origin

**Tracking Advance**:
One accepted extension of a DailyTrack through a fixed contiguous set of later Research Sessions, producing a complete new tracking result or leaving the previous result unchanged.
_避免混用_: ResearchRun, Data Refresh, partial result

**DailyTrack Refresh**:
The explicit request to advance an active DailyTrack that has newer data available and no unfinished advance.
_避免混用_: Data Refresh, viewing status, automatic tracking

**Tracking Advance Target**:
The oldest consecutive Research Sessions not yet included in the DailyTrack that one accepted Tracking Advance will cover.
_避免混用_: The entire current backlog, a changing target

**Tracking Progress**:
The latest completed Research Session of a DailyTrack, its remaining lag, and whether its requested advance is unfinished.
_避免混用_: A provisional result, elapsed-time completion

**Batch-Incremental Equivalence**:
The requirement that historical Research and successive Daily Tracking produce identical research findings from identical inputs and origin state.
_避免混用_: Research Batch, approximate similarity, a rolling backtest

## Strategy Execution

**Strategy**:
The rules that translate Alpha Values into portfolio targets and changes over
time.
_避免混用_: Alpha, Factor, Investment Hypothesis

**Strategy Candidate Order**:
The deterministic order used to select equal-weight targets and prioritize buy
deficits at a Rebalance.
_避免混用_: Source order, Factor quantile rank

**Holdings Count**:
The explicit maximum number of Top-N targets selected by a Strategy.
_避免混用_: Filled-position guarantee, percentage cutoff

**Initial Cash**:
The fixed all-cash Gross and Net NAV baseline from which a Strategy Backtest
starts.
_避免混用_: Current cash, deployable cash after costs

**Rebalance**:
A scheduled Strategy decision that replaces the complete Target Portfolio using
the signal session's Final Alpha Cross-Section.
_避免混用_: Every-session signal cohort, Factor Label

**Target Portfolio**:
The ideal equal-weight allocation selected at a Rebalance before execution
constraints are applied.
_避免混用_: Actual Holdings, guaranteed allocation

**Actual Holdings**:
The positions and cash that remain after order eligibility, costs, and quantity
rules are applied to a Target Portfolio.
_避免混用_: Target Portfolio, pending order

**Execution Share Quantity**:
The non-negative integer share coordinate used for Strategy orders and market
execution constraints.
_避免混用_: Adjusted Holding Units, broker share ledger

**Adjusted Holding Units**:
The possibly fractional quantity used with Adjusted Research Price to value an
Actual Holding through corporate actions.
_避免混用_: Execution Share Quantity, broker share balance

**Research Settlement**:
The synthetic cash value transferred when Adjusted Holding Units are removed by
a Strategy sale.
_避免混用_: Raw notional, broker settlement, company-action event

**Actual Holdings Count**:
The number of instruments with positive Execution Share Quantity after an open
execution cycle.
_避免混用_: Holdings Count, candidate count, order count

**Maximum Single-Name Weight**:
The largest Actual Holding value as a share of post-trade Net NAV.
_避免混用_: Target equal weight, configured cap

**Cash Ratio**:
Post-trade Net Cash divided by Net NAV.
_避免混用_: Cash target, Initial Cash

**Valuation Carry**:
The last valid Adjusted Research Price used only to value a confirmed
full-session-suspended Actual Holding.
_避免混用_: Forward fill, executable price, synthetic market bar

**Terminal Delisting Write-Off**:
The zero-value removal of an Actual Holding when effective terminal delisting makes its required Open unavailable.
_避免混用_: Forced sale, Valuation Carry, unexplained missing data

**Terminal Delisting Return**:
The synthetic `-100%` return used when explicit terminal delisting makes a valid
Forward Return Label exit unavailable.
_避免混用_: Observed zero-price trade, missing-entry return

**Board-Lot Rounding**:
The conversion of an intended order value into an exchange-valid integer
Execution Share Quantity.
_避免混用_: Fractional share, universal lot rule

**Child Order**:
One exchange-limit-compliant piece of a larger logical Strategy order.
_避免混用_: Partial fill, replacement order

**Transaction Costs**:
The fixed deductions charged to filled Strategy orders under the current
research cost contract.
_避免混用_: Slippage, market impact, hidden fee

**Transaction Cost Return Drag**:
Gross Cumulative Return minus Net Cumulative Return from the same fill path.
_避免混用_: Annualized drag, relative return ratio

**Turnover**:
The half-sum of absolute same-open changes in actual instrument and cash weights.
_避免混用_: Order count, target-weight change

**Rebalance Interval**:
The number of Research Sessions between scheduled Strategy signal sessions.
_避免混用_: Natural-day interval, holding cohort

**Open Execution Model**:
The synthetic contract that attempts eligible Strategy orders at the next
Research Session's Raw Market Price Open.
_避免混用_: Intraday model, Adjusted execution price

**Blocked Order**:
A Strategy order that cannot execute at its single scheduled Open and is not
retried or substituted.
_避免混用_: Pending order, partial fill

**Market Rejection**:
A logical Strategy order blocked by a governed price-limit or full-session
suspension condition.
_避免混用_: Insufficient cash, invalid data, below-lot omission

**Trading State**:
The classification of an instrument as having a valid traded session, a confirmed full-session suspension, or unavailable market evidence for a Research Session.
_避免混用_: Missing data assumed to be suspension, pending order

**Existing-Position Eligibility**:
The scheduled reassessment of whether an Actual Holding remains eligible for the
new Target Portfolio.
_避免混用_: Immediate liquidation, permanent eligibility

## Strategy Results

**Strategy Backtest**:
The historical portfolio result produced by applying Strategy execution, costs,
and adjusted valuation to Alpha Values.
_避免混用_: Factor Evaluation, broker statement

**Strategy Daily Observation**:
The minimal retained Strategy result for one Research Session.
_避免混用_: Position history, order ledger, fill ledger

**Terminal Strategy State**:
The ending holdings, cash, and accumulated performance of a Strategy Backtest or Tracking Advance.
_避免混用_: The full trading history, one daily observation

**Gross NAV**:
Gross Cash plus the adjusted value of Actual Holdings before Transaction Costs.
_避免混用_: Net NAV, Target Portfolio value

**Net NAV**:
Net Cash plus the adjusted value of Actual Holdings after Transaction Costs.
_避免混用_: Gross NAV, pre-trade NAV

**Cumulative Return**:
Ending NAV divided by the common Initial Cash baseline, minus one.
_避免混用_: Annualized Return, summed daily return

**Annualized Return**:
The compound growth rate of a NAV series expressed on the research calendar’s annual basis.
_避免混用_: Cumulative Return, Annualized Volatility

**Net Excess NAV**:
Net NAV growth divided by one plus Benchmark Relative Return from the same
investable baseline.
_避免混用_: Return subtraction, Gross excess

**Annualized Excess Return**:
The compound growth rate of Net Excess NAV expressed on the research calendar’s annual basis.
_避免混用_: Difference of two annualized returns

**Maximum Drawdown**:
The largest peak-to-trough loss magnitude in Net NAV over the Research Period.
_避免混用_: Gross drawdown, single-session loss

**Annualized Volatility**:
The annualized sample standard deviation of consecutive Daily Net Returns.
_避免混用_: NAV-level volatility, Gross volatility

**Sharpe Ratio**:
The annualized mean Daily Net Return relative to its variability under the research risk-free-rate assumption.
_避免混用_: Compound growth divided by volatility, Gross Sharpe

**Calmar Ratio**:
Net Annualized Return divided by Maximum Drawdown.
_避免混用_: Sharpe Ratio, infinite zero-drawdown result

**Open NAV Cycle**:
The daily Strategy accounting sequence from pre-trade valuation through open
execution to the post-trade NAV observation.
_避免混用_: Close NAV, intraday marking

**Backtest Start Baseline**:
The all-cash observation at the first Research Period Open before any Strategy
position exists.
_避免混用_: Warm-up position, first holding return

**Terminal Valuation**:
The final Research Period Open valuation recorded without another Rebalance or
forced liquidation.
_避免混用_: Final Rebalance, hypothetical exit

**Strategy Benchmark**:
The fixed CSI 300 Price Index used to compare Strategy performance over the same
Open-to-Open interval beginning at the first investable Entry Open.
_避免混用_: Selected-universe benchmark, configurable benchmark, total-return index

**Benchmark Level**:
The official CSI 300 Price Index Open point for one Research Session.
_避免混用_: Benchmark NAV, benchmark return, constituent average

**Benchmark Snapshot**:
The current accepted history of Benchmark Levels used for Strategy Comparison.
_避免混用_: Data Generation, a ResearchRun-specific benchmark

**Benchmark Relative Return**:
The Benchmark Level divided by its level at the first investable Entry Open,
minus one.
_避免混用_: Benchmark NAV, daily pct_chg, return since 2010

**Strategy Comparison**:
The comparison of fixed Strategy performance with the available Strategy Benchmark over the same entry-to-terminal Open interval.
_避免混用_: Strategy execution, Factor Evaluation

## Dataset and Market Data

**End-of-Day Research**:
Research over completed Shanghai and Shenzhen A-share Research Sessions using
daily-granularity information available after the session closes.
_避免混用_: Intraday research, real-time research, live trading

**Research Calendar**:
The ordered intersection of dates on which both the SSE and SZSE are open.
_避免混用_: Natural-day calendar, one-exchange union

**Research Session**:
One completed date in the Research Calendar.
_避免混用_: Calendar day, source row, intraday session

**Requested Research Dates**:
The inclusive natural-date range requested for a ResearchRun, within which its
Research Period is selected.
_避免混用_: Session indexes, inferred dates, Calculation Warm-up

**Research Period**:
The ordered Research Sessions inside Requested Research Dates and the sole
period reported by Factor Evaluation and Strategy Backtest.
_避免混用_: Complete history, Calculation Warm-up

**Calculation Warm-up**:
The Research Sessions before a Research Period required only to evaluate the
Alpha Formula's Effective Alpha Lookback.
_避免混用_: Research Period, reported results

**Dataset Head**:
The currently accepted Data Generation available to new research.
_避免混用_: Historical research inputs, a ResearchRun result

**Data Generation**:
A mutually consistent collection of validated Canonical Data fixed as the input to accepted research.
_避免混用_: User-selectable data history, Result Bundle

**Dataset Coverage**:
The verified extent declared by one Dataset Family inside a Data Generation.
_避免混用_: Requested Research Dates, universal date range

**Market Coverage**:
The Dataset Coverage of end-of-day market families through one completed
Research Session.
_避免混用_: Financial Coverage, Research Period

**Benchmark Coverage**:
The Research Session extent for which the current Benchmark Snapshot can support
Strategy Comparison.
_避免混用_: Dataset Coverage, Data Generation, lagging benchmark, carried level

**Financial Coverage**:
The quality-bearing Dataset Coverage of Point-in-Time Financial Data, including
its discovery baseline, attempted-through and complete-through coordinates,
pending instruments, discovery gaps, and reconciliation limits.
_避免混用_: One observation-through date, non-null guarantee, market date range

**Financial Coverage Start**:
The first Research Session from which the bootstrap financial family can resolve
covered Source Financial Versions under its declared revision limits.
_避免混用_: Financial Discovery Baseline, earliest retained row, source request start

**Financial Discovery Baseline**:
The accepted financial observation boundary after which continuous announcement discovery begins.
_避免混用_: Financial Coverage Start, oldest retained report

**Financial Seed Fact**:
A pre-Coverage Financial Fact retained only to resolve a correct
Session-Aligned Financial Field at Financial Coverage Start.
_避免混用_: Earlier Financial Coverage, invented value

**Financial Research Readiness**:
The quality status indicating whether financial inputs are usable for research and whether known pending updates or discovery gaps remain.
_避免混用_: Complete Financial Coverage, a guarantee that every field has a value

**Dataset Bootstrap**:
The initial preparation of Canonical Data that establishes the first Data Generation available for research.
_避免混用_: Data Refresh, research admission

**Data Refresh**:
An Operator-requested update of shared Canonical Data that either publishes a validated Data Generation, confirms no change, or reports failure.
_避免混用_: DailyTrack Refresh, ResearchRun, completed publication on submission

**Data Refresh Operation**:
The accepted request and eventual outcome of one Market, Financial, or Industry Refresh.
_避免混用_: Published Data Generation, an automatic recurring update

**Market Refresh**:
A Data Refresh that advances end-of-day market families while retaining the
current financial families.
_避免混用_: Financial Refresh, independent Dataset Head

**Financial Refresh**:
A Data Refresh of affected instruments’ financial statements that preserves prior accepted facts for unsuccessful instruments and leaves market facts unchanged.
_避免混用_: Market Refresh, complete Financial Coverage, publication on collection

**Financial Announcement Discovery**:
The observed disclosures and corrections that identify possible financial updates or reveal gaps in announcement coverage.
_避免混用_: Financial statement values, completed Financial Refresh

**Financial Discovery Attempted Through**:
The latest Research Session through which a Financial Refresh published either
complete announcement evidence or explicit discovery gaps.
_避免混用_: Financial Discovery Complete Through, implicit success

**Financial Discovery Complete Through**:
The latest Research Session through which every declared announcement category
and page has been observed without an unresolved Financial Discovery Gap.
_避免混用_: Financial Discovery Attempted Through, statement freshness

**Financial Discovery Gap**:
An interval or disclosure category whose incomplete announcement evidence leaves some affected instruments unknown.
_避免混用_: A known instrument’s failed update, complete discovery

**Financial Announcement Trigger**:
An observed disclosure or correction requiring an affected instrument’s financial facts to be rechecked. It is resolved only by a validated change or a validated finding of no change.
_避免混用_: Financial Fact, exact disclosure-to-version correspondence, successful collection alone

**Canonical Data**:
The accepted market, reference, industry, and financial facts with governed meaning and information availability for research.
_避免混用_: Raw source observations, Research results

**Canonical Market Data**:
The accepted market and reference facts with defined units, meaning, and availability for research.
_避免混用_: Unvalidated source observations, Financial Facts

**Raw Market Price**:
The unadjusted nominal OHLC price quoted in CNY for one instrument and Research
Session.
_避免混用_: Adjusted Research Price, qfq price

**Adjusted Research Price**:
The corporate-action-continuous price coordinate used for Alpha and return
calculations rather than market execution.
_避免混用_: Raw Market Price, quoted execution price

**Source Adjustment Factor**:
The positive dated adjustment fact associated with an instrument and Research Session.
_避免混用_: Adjusted Research Price, Strategy parameter

**Adjustment Scale**:
The same-session scale applied to Raw Market Price to produce Adjusted Research
Price.
_避免混用_: Latest-factor anchor, Raw Market Price

**Field Catalog**:
The inventory of Canonical Fields and their research meaning.
_避免混用_: Alpha Authoring Catalog, source documentation

**Canonical Field**:
A named kind of Canonical Data with a fixed meaning, unit, observation grain, and information-availability rule.
_避免混用_: Source column label, a change to the field’s meaning

**Dataset Family**:
A group of Canonical Fields sharing the same instrument scope, observation grain, and information-availability semantics.
_避免混用_: A data supplier, one universal table of facts

**Instrument Identity**:
The stable identity of one supported market instrument across its Canonical Data and research results.
_避免混用_: Display name, one market observation

**Point-in-Time Financial Data**:
Financial facts visible only from their governed disclosure and observation dates, so later information cannot become available to earlier research.
_避免混用_: A current statement treated as historical, rewritten tracking history

**Source Financial Version**:
One financial statement version actually observed from the data source, together with its reporting, publication, and first-observation context.
_避免混用_: An invented revision, Financial Fact, a current-only statement

**Financial Fact**:
One nullable Canonical numeric measurement from a Source Financial Version with
its reporting and availability context.
_避免混用_: Filled zero, daily Alpha field

**Consolidated Reporting Scope**:
The reporting boundary that combines a listed parent and controlled subsidiaries
while preserving parent-owner attribution.
_避免混用_: Parent-only statement, mixed scope

**Session-Aligned Financial Field**:
A Canonical financial field that resolves to at most one value per Instrument
Identity and Research Session under fixed point-in-time semantics.
_避免混用_: Raw statement column, implicit latest report

**Latest Annual Financial Field**:
A Session-Aligned Financial Field that selects the latest available full-year
Financial Fact.
_避免混用_: TTM field, latest interim report

**Latest Reported Stock Field**:
A Session-Aligned Financial Field that selects the latest available
balance-sheet Financial Fact regardless of report period.
_避免混用_: Annual-only stock, period average

**Financial Field Applicability**:
The explicit company-type set for which a Session-Aligned Financial Field has a
comparable meaning.
_避免混用_: Hidden company filter, zero fill

## Universe and Industry

**Universe Base Pool**:
The point-in-time set of ordinary SSE and SZSE A-shares eligible for liquidity
ranking before research-specific filters are applied.
_避免混用_: Current-listed-only list, Research Eligibility

**Liquidity Universe**:
A daily ranked selection from the Universe Base Pool based on trailing completed
session turnover amount.
_避免混用_: Static stock list, index constituents, tradability filter

**Liquidity Rank**:
The unique deterministic position of one instrument in a daily Liquidity
Universe ordering.
_避免混用_: Source order, independent Top-N rank

**Liquidity Observation Window**:
The governed completed-session history used to calculate one instrument's
Liquidity Rank.
_避免混用_: Last non-missing observations, silent zero fill

**Universe Membership**:
The ranked instruments selected by one Liquidity Universe for one Research
Session.
_避免混用_: Universe definition, permanent member list

**Research Eligibility**:
The downstream decision about which Universe Membership instruments may enter a
signal session's Alpha, Factor, and new-buy calculations.
_避免混用_: Liquidity ranking, permanent exclusion

**Industry Classification**:
The point-in-time primary SW2021 industry path of an instrument for a Research Session.
_避免混用_: Raw overlapping memberships, current industry applied to all history, Liquidity Universe

**Industry Neutralization**:
The optional cross-sectional demeaning of Alpha Values within each instrument's
point-in-time SW2021 L1 industry.
_避免混用_: Separate Research Kind, automatic neutralization
