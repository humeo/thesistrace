# Point-in-Time Financial Data and Composite Alpha

**Status:** complete

## Problem Statement

ThesisTrace currently supports research over a small set of end-of-day market
fields. A researcher cannot safely combine those fields with company financial
statements in one Alpha Formula, run the Formula over historical sessions, and
continue the same research through a DailyTrack.

TuShare can return hundreds of income-statement, balance-sheet, and cash-flow
fields, but those source columns are not directly comparable daily Alpha
inputs. A source row has a report period, reporting scope, company type,
announcement date, update marker, and potentially multiple returned versions.
Flow values may be annual or cumulative interim amounts, while balance-sheet
values are point-in-time stocks. Treating a raw source column as an ordinary
daily series, selecting the latest row without an information-time cutoff, or
filling missing values with zero would create ambiguous research semantics and
look-ahead bias.

The current data contract also assumes one flat, fixed set of end-of-day
tables. Execution opens the complete Data Generation and the Alpha evaluator
knows physical price columns directly. Adding wide financial statements to that
path would make claim and execution slower, couple the Research Kernel to
storage, and make market-only research pay the financial-data cost.

The product therefore needs a complete Point-in-Time Financial Data slice:
immutable source evidence, preserved source versions, family-specific
Coverage, a selective Data-owned Series reader, a small set of unambiguous
financial fields, mixed market-financial Alpha composition, and identical
ResearchRun and DailyTrack behavior. It must publish atomically under the
existing single Dataset Head and must not introduce a second financial Head,
runtime fallback, or partially usable financial dataset.

## Solution

Add an equity.financial_pit Dataset Family sourced from the ordinary
per-instrument TuShare income, balance-sheet, and cash-flow endpoints. Preserve
each accepted response as a content-addressed Raw Financial Batch and preserve
all returned fields and source versions in three nullable wide Canonical
version tables. Financial facts remain sparse and revision-aware; they are not
permanently expanded into daily rows.

Add a Data-owned point-in-time Series reader that resolves requested stable
Field References for the pinned Data Generation, selected instruments, and
Research Sessions. The six initial Session-Aligned Financial Fields use
namespaced stable Field References and expose these short Alpha Identifiers:

- total_revenue_latest_fy;
- net_profit_parent_latest_fy;
- operating_cash_flow_latest_fy;
- total_assets_latest_reported;
- total_liabilities_latest_reported;
- equity_parent_latest_reported.

The three flow fields use the latest available full-year consolidated
statement. The three stock fields use the latest available quarterly or annual
consolidated balance sheet. All six apply to TuShare company types 1 through 4,
retain source missingness, and never fall back to another reporting scope.
Trailing-twelve-month values are not constructed in this first slice.

Extend the Alpha Authoring Catalog with those six fields and one
cross-sectional builtin, cs_rank. A Composite Alpha remains one Alpha Formula;
there is no separate factor-list or multi-factor-model resource. The existing
Alpha Execution Plan evaluates market and financial children once, ranks each
complete selected-universe cross-section, and passes the resulting Numeric
Series through the same Research Kernel used by ResearchRun and DailyTrack.

Replace the flat Generation read boundary with one root Manifest that references
family Manifests. Market Refresh and Financial Refresh remain separate private
Data Operator actions, but each publishes one fully validated root through the
single Dataset Head and reuses every unchanged family Manifest and Physical
Data Object. Claim and pin inspect only the Head and root descriptor. Execution
opens only the family objects, partitions, and columns required by the admitted
Formula.

Financial Coverage starts at the first Research Session of 2010, with only the
minimal pre-start Financial Seed Facts required to resolve the first covered
session. The first financial-capable Head also provides Market Coverage from
the same 2010 session. Data Overview reports Market Coverage, Financial
Coverage, observation cutoffs, refresh timestamps, and all-or-nothing Financial
Research Readiness. Financial data becomes visible to Alpha authoring only when
the raw evidence, Canonical facts, Series reader, initial field capabilities,
ResearchRun path, DailyTrack path, and performance gates all pass together.

## User Stories

1. As a researcher, I want to discover the initial financial fields in the
   Alpha Authoring Catalog, so that I can use supported financial meanings
   without learning TuShare transport columns.
2. As a researcher, I want each financial field to have a stable identifier,
   unit, time semantic, and description, so that a saved Formula retains one
   precise meaning.
3. As a researcher, I want to combine market and financial Numeric Series in
   one Alpha Formula, so that I can build a Composite Alpha without a separate
   multi-factor product.
4. As a researcher, I want to apply arithmetic and existing Alpha Builtins to
   financial fields, so that financial and market inputs remain fully
   composable.
5. As a researcher, I want cs_rank to normalize child factors within each
   selected-universe session, so that factors with different units can be
   weighted explicitly.
6. As a researcher, I want lower-is-better factors to require explicit
   negation, so that factor direction is visible in the Formula.
7. As a researcher, I want the completed Composite Alpha to retain the
   platform's higher-is-more-bullish direction, so that Factor Evaluation and
   Strategy selection remain coherent.
8. As a researcher, I want Industry Neutralization to run after the complete
   Formula, so that the Formula's factor composition is not changed
   implicitly.
9. As a researcher, I want to run financial research from the first Research
   Session of 2010, so that the advertised financial history has a clear
   executable beginning.
10. As a researcher, I want values to become usable only after their source
    publication is available to the market, so that historical results do not
    look ahead.
11. As a researcher, I want an annual revenue field to mean the latest
    available full-year value, so that it never silently mixes Q1, half-year,
    nine-month, and full-year cumulative periods.
12. As a researcher, I want annual parent net profit to use the
    parent-owner-attributable value from a consolidated statement, so that the
    reporting scope is consistent.
13. As a researcher, I want annual operating cash flow to use the latest
    available full-year consolidated value, so that it has the same period
    selection rule as the other initial flow fields.
14. As a researcher, I want balance-sheet fields to use the latest available
    reported quarter or year end, so that stock quantities reflect the newest
    known reporting point.
15. As a researcher, I want annual fields to remain distinct from TTM fields,
    so that convenience calculations do not change the meaning of the initial
    product.
16. As a researcher, I want source nulls and unavailable values to remain
    missing, so that absent financial evidence is never presented as zero.
17. As a researcher, I want the six initial fields to support general
    industrial, banking, insurance, and securities companies, so that the
    authorable universe is not restricted by company type.
18. As a researcher, I want a missing statement for one instrument to remain a
    visible missing Alpha input, so that the platform does not silently change
    my Liquidity Universe.
19. As a researcher, I want a revised financial value to affect only sessions
    on or after its availability, so that earlier results retain the knowledge
    available at that time.
20. As a researcher, I want a ResearchRun to freeze its resolved Field
    References and Data Generation provenance, so that the result is auditable.
21. As a researcher, I want a market-financial ResearchRun to reject a period
    that exceeds Financial Coverage, so that stale financial data is not
    silently treated as current.
22. As a researcher, I want market-only ResearchRuns to depend only on Market
    Coverage, so that a slow or failed Financial Refresh does not block market
    research.
23. As a researcher, I want the same Formula, field semantics, and cs_rank
    behavior in ResearchRun and DailyTrack, so that forward tracking does not
    drift from the backtest.
24. As a DailyTrack owner, I want a financial Track to advance through every
    covered Research Session, so that the Composite Alpha continues
    forward-only.
25. As a DailyTrack owner, I want a financial Track to block before the first
    session beyond the financial observation cutoff, so that incomplete
    financial knowledge is never guessed.
26. As a DailyTrack owner, I want the blocked Track to resume after a complete
    Financial Refresh advances Coverage, so that the same immutable research
    can continue safely.
27. As a DailyTrack owner, I want a market-only Track to keep advancing when
    financial data is behind, so that unrelated family readiness is not a
    global gate.
28. As a user, I want Data Overview to show Market Coverage and Financial
    Coverage separately, so that I understand which data product supports a
    requested period.
29. As a user, I want Data Overview to distinguish Financial Coverage from
    non-null availability for every company, so that sparse facts are not
    mistaken for an incomplete refresh.
30. As a user, I want Financial Research Readiness to be all-or-nothing, so
    that seeing financial fields means they work through both ResearchRun and
    DailyTrack.
31. As a user, I want Data Overview to show observation cutoffs and last
    refresh times, so that I can understand how current each family is.
32. As a user, I want the initial interface to focus on Alpha authoring and
    readiness, so that I am not forced through a raw statement browser to use
    financial research.
33. As a Data Operator, I want Bootstrap to enumerate the historical ordinary
    A-share Instrument Identity set, so that delisted stocks are included and
    survivorship bias is avoided.
34. As a Data Operator, I want one deterministic ordinary-interface
    endpoint-by-instrument shard contract, so that collection behavior is
    deployable with the selected TuShare permission tier.
35. As a Data Operator, I want each completed shard checkpointed durably, so
    that a multi-hour Bootstrap or Financial Refresh can resume after failure.
36. As a Data Operator, I want a capability probe to prove permissions,
    fields, limits, and response completeness before collection, so that an
    apparently successful but truncated response is not published.
37. As a Data Operator, I want an incomplete or ambiguous response to fail
    closed, so that the collector never switches silently to a weaker contract.
38. As a Data Operator, I want every V1 Financial Refresh to re-request the
    complete expected historical shard set, so that all source-visible
    historical changes use one completeness rule.
39. As a Data Operator, I want exact duplicate batches and objects reused by
    content identity, so that full refresh does not duplicate unchanged bytes.
40. As a Data Operator, I want previously accepted Source Financial Versions
    retained when the latest response omits them, so that source absence never
    destroys audit history.
41. As a Data Operator, I want Market Refresh and Financial Refresh to be
    independent actions, so that multi-hour financial collection does not
    delay normal market publication.
42. As a Data Operator, I want both refresh actions to publish through one
    Dataset Head, so that execution never joins independently moving market and
    financial snapshots.
43. As a Data Operator, I want concurrent refresh publication fenced by the
    expected Head, so that a stale root cannot overwrite a newer Generation.
44. As a Data Operator, I want a stale family candidate recombined with the
    latest unchanged family Manifests and revalidated, so that useful completed
    collection is not discarded or published inconsistently.
45. As a Data Operator, I want partial collection and candidate artifacts to
    remain unpublished, so that ordinary users never encounter an ingestion-only
    financial Head.
46. As an auditor, I want every accepted source response retained with request
    parameters, collection time, schema, row count, and digest, so that a
    Canonical value can be traced to evidence.
47. As an auditor, I want report type, company type, report period,
    announcement dates, update marker, and source payload identity preserved,
    so that distinct reporting versions are not overwritten.
48. As an auditor, I want source-provided revisions distinguished from
    observed corrections, so that a silently changed payload is not backdated
    to an unsupported publication date.
49. As an auditor, I want revision-coverage limitations declared in Financial
    Coverage, so that ThesisTrace does not claim versions TuShare never
    returned.
50. As a platform maintainer, I want all pinned source-contract fields retained
    while only explicitly session-aligned fields are authorable, so that future
    products can reuse evidence without exposing ambiguous factors now.
51. As a platform maintainer, I want the Data module to own physical field
    resolution, so that the Research Kernel does not know Parquet tables,
    manifests, vendor fields, or point-in-time joins.
52. As a platform maintainer, I want claim and pin to read only the Dataset Head
    and root descriptor, so that queued-to-running latency does not scale with
    all data objects.
53. As a platform maintainer, I want market-only Formulae to read no financial
    objects, so that financial breadth has no I/O cost for unrelated research.
54. As a platform maintainer, I want mixed Formulae to read only requested
    fields, columns, sessions, instruments, and partitions, so that execution
    remains bounded at the 2010-scale dataset.
55. As a platform maintainer, I want old Physical Data Objects retained while
    an Attempt or active Generation references them, so that concurrent refresh
    and execution cannot invalidate pinned reads.
56. As a platform maintainer, I want unreferenced old objects to become
    garbage-collectable, so that immutable Generations do not imply permanent
    full-data retention.
57. As a quality owner, I want one deterministic end-to-end financial fixture
    to exercise Data Operator, ResearchRun, and DailyTrack, so that the product
    slice is proven rather than inferred from isolated components.
58. As a quality owner, I want source-contract tests to avoid public network
    access, so that CI is fast, repeatable, and independent of TuShare account
    state.
59. As a quality owner, I want batch and incremental execution compared for
    exact equality, so that DailyTrack cannot develop a second financial or
    ranking implementation.
60. As a quality owner, I want representative I/O and memory benchmarks before
    publication, so that the new data family does not recreate the previous
    full-Generation loading bottleneck.

## Implementation Decisions

### Product boundary and dependency

- This specification extends the accepted Alpha Language and Research Workspace
  design. One Formula, stable Field References, the Data-owned Alpha Field
  Catalog, the Series Execution Plan, ResearchRun admission, and DailyTrack
  continuation remain the product foundations.
- The financial capability ships as one complete executable slice. It is not
  published in stages as raw-only, table-only, ResearchRun-only, or
  DailyTrack-later functionality.
- The initial user surfaces are the Alpha Authoring Catalog, Formula editor,
  Data Overview, ResearchRun results, and DailyTrack. There is no separate
  financial-analysis application.

### Source and collection contract

- TuShare remains the sole upstream source. The first financial collector uses
  only the ordinary per-instrument income, balance-sheet, and cash-flow
  endpoints. VIP endpoints, another provider, and runtime transport fallback
  are prohibited.
- Collection uses resumable endpoint-by-instrument shards over the historical
  ordinary A-share Instrument Identity set. Each shard has a deterministic
  request contract, expected response schema, completion evidence, and durable
  checkpoint.
- A deployment capability probe must establish endpoint permission, actual
  fields, rate-limit behavior, duplicate patterns, null behavior, and whether a
  complete-history response is complete. If one response cannot be proven
  complete, implementation must select one deterministic date-shard contract
  before collection; it may not change request shapes at runtime.
- Every accepted response is a Raw Financial Batch addressed by its exact
  content and accompanied by endpoint, parameters, returned field order,
  collection time, row count, first and last source dates, and payload digest.
- Schema drift, missing permission, suspected truncation, incomplete shards,
  invalid dates, or cross-family invariant failure prevents publication.
  Retried or resumed collection never relaxes those requirements.

### Canonical financial model

- Point-in-Time Financial Data is a separate equity.financial_pit Dataset
  Family. It is not an extension of the end-of-day price table.
- Income statements, balance sheets, and cash-flow statements are stored as
  three separate wide Canonical version tables. One row represents one Source
  Financial Version, and every field in the pinned source contract is retained
  in its corresponding nullable column.
- Each version retains Instrument Identity, source endpoint, report period,
  report type, company type, end type, announcement and final-announcement
  dates, source publication date, first observation time, source and effective
  availability sessions, update marker, revision basis, source row digest, Raw
  Financial Batch digest, and all statement values.
- Source row identity includes the endpoint, instrument, report period,
  reporting scope, source dates, and canonical source payload. Exact rows are
  idempotent. A logical revision group excludes the payload digest so multiple
  accepted versions can coexist.
- All report types and company types returned by the in-scope source contracts
  are retained. Report type 1 is not used as an ingestion filter; it is a
  projection rule for the initial authorable fields.
- Raw and Canonical nulls stay null. No collection, mapping, Series reading,
  Alpha evaluation, or neutralization step fills them with zero.
- Canonical tables remain sparse version facts. Session-aligned values are
  resolved on demand and are not persisted as a permanent
  instrument-by-session expansion.

### Information-time and revision semantics

- Source publication uses the final announcement date when present and the
  announcement date otherwise. Both original fields remain preserved.
- Because the source provides date-level rather than trustworthy intraday
  publication time, a source version first becomes available on the next
  completed Research Session determined by the canonical research calendar.
- A source-provided version uses its mapped source availability session. If the
  same logical source version later has a different payload without a new
  verifiable source publication date, it is an observed correction and becomes
  usable no earlier than the session in which that payload was first observed.
- A missing usable publication date quarantines the row from authorable
  Point-in-Time Financial Data. The system does not synthesize a date from the
  report period or a fixed reporting delay.
- The system preserves every Source Financial Version TuShare actually
  provides but never claims or fabricates intermediate revision history that
  the source does not expose.

### Coverage, Bootstrap, and readiness

- Dataset Coverage belongs to each Dataset Family, not to a ResearchRun. A Run
  only validates that the families referenced by its frozen Field References
  cover the required calculation slice.
- Market Coverage remains an inclusive Research Session range. Financial
  Coverage records Financial Coverage Start, the complete expected shard set,
  financial observation-through cutoff, historical reconciliation watermark,
  and source revision-coverage limitations.
- Missing Financial Facts for individual instruments are valid sparse data and
  are not equivalent to incomplete Financial Coverage.
- Financial Coverage Start is the first Research Session of 2010. The first
  financial-capable Dataset Head must also provide Market Coverage from that
  session.
- Canonical financial versions include every accepted source version that
  becomes available on or after Financial Coverage Start, irrespective of the
  report period. For instruments already in scope at the start, only the latest
  pre-start full-year facts and latest pre-start balance-sheet facts needed by
  the initial fields are retained as Financial Seed Facts.
- A complete-history source response may contain older rows. Those bytes remain
  in Raw Financial Batch evidence, but rows outside Financial Coverage that are
  not required seeds do not become Canonical Financial Facts and do not extend
  Coverage backward.
- Financial Research Readiness is published only when source evidence,
  Canonical tables, family Coverage, the Series reader, all six field
  capabilities, ResearchRun, DailyTrack, and performance acceptance are
  complete for the same candidate Generation.

### Generation, pinning, and physical ownership

- One Dataset Head points to one immutable Data Generation root. The root
  references separate family Manifests, including market families,
  equity.financial_pit, and the Field Catalog.
- A family Manifest declares its Dataset Schema, Coverage, partitions, Physical
  Data Objects, raw evidence references where applicable, and validation
  summary. The root aggregates family declarations without converting them
  into one global intersection.
- Market Refresh and Financial Refresh materialize only their target families
  and reuse every unchanged family Manifest and content-addressed object.
- Publication compares against the Dataset Head observed when candidate
  composition began. If the Head changed, the stale root is not published; the
  completed target family is combined with the latest unchanged families and
  all cross-family invariants are revalidated.
- ResearchRun admission retains one root descriptor and each ResearchRun
  Attempt atomically replaces that retention with a pin to the same root.
  Tracking Advance Attempts select and pin one current root when they start.
  Claim and pin do not enumerate or open all Parquet objects.
- The pinned root identifies the exact family Manifests used throughout the
  Attempt. A concurrent Data Refresh may publish another root, but it cannot
  change the active Attempt's reads.
- Generation and execution references protect required family Manifests, Raw
  Financial Batches, and Physical Data Objects from garbage collection. Objects
  become collectible only after no published Generation, active pin, retained
  result provenance, or other durable ownership rule references them.

### Refresh lifecycle

- Market Refresh and Financial Refresh are separate private, manually triggered
  Data Operator actions. Neither is exposed as an ordinary web or public API
  action, and V1 has no automatic financial schedule.
- Market Refresh keeps its bounded market overlap and new-session behavior and
  reuses the current financial family unchanged.
- Every V1 Financial Refresh re-requests the complete historical expected shard
  set for all three statement endpoints and the current historical Instrument
  Identity set. There is no hot-window, rotating-reconciliation, or recent-only
  mode.
- Financial Refresh resumes incomplete shards from checkpoints, content-reuses
  exact duplicates, and builds the union of previously accepted Source
  Financial Versions and newly observed versions. A version absent from a later
  source response is not deleted.
- No partial success moves the Dataset Head. Candidate objects and Manifests may
  exist beside the active store for validation, but they remain undiscoverable
  to ordinary authoring until the whole candidate publishes.

### Field Catalog and Series-reading boundary

- Data owns Canonical Field Definitions, Alpha Field Capabilities, physical
  bindings, availability rules, units, missingness, company-type
  applicability, and Series reading. The Alpha Language owns Builtin
  Definitions. The Research Kernel owns neither storage concern.
- Alpha compilation resolves a short authoring identifier to a stable Canonical
  Field Reference. The admitted Expression stores that stable reference rather
  than a TuShare name or physical table column.
- Execution derives the requested Field References from the admitted
  Expression and asks the pinned Data Generation for aligned Numeric Series
  over the required sessions and instruments. The returned Alpha input matrix
  is the storage-independent boundary consumed by the Research Kernel.
- Market readers and the financial point-in-time reader implement the same
  Data-owned operation. The financial reader selects the latest visible version
  inside each logical revision group and then applies the field's fixed report
  period and reporting-scope rule.
- Series resolution is batched and vectorized. It must not scan one file per
  instrument or iterate through an instrument-by-session-by-field grid in
  Python.
- Data Overview and admission inspect family descriptors and capabilities
  without opening financial Parquet. Execution projects only required columns,
  partitions, sessions, and instruments.

### Initial financial fields

- Their stable Field References are
  `financial.income.total_revenue.latest_fy`,
  `financial.income.net_profit_parent.latest_fy`,
  `financial.cashflow.operating_cash_flow.latest_fy`,
  `financial.balance_sheet.total_assets.latest_reported`,
  `financial.balance_sheet.total_liabilities.latest_reported`, and
  `financial.balance_sheet.equity_parent.latest_reported`. Formulae use the
  corresponding short names below.
- The first three flow Alpha Identifiers are total_revenue_latest_fy,
  net_profit_parent_latest_fy, and operating_cash_flow_latest_fy. They select
  the latest visible full-year report_type 1 consolidated facts from income and
  cash-flow statements.
- The first three stock Alpha Identifiers are total_assets_latest_reported,
  total_liabilities_latest_reported, and equity_parent_latest_reported. They
  select the latest visible quarterly or annual report_type 1 consolidated
  balance-sheet facts.
- The initial six fields apply to company types 1, 2, 3, and 4. Applicability
  means the field definition is valid for those company types; it does not
  promise a non-null value or claim that one economic weighting is appropriate
  across all industries.
- No other retained source field is Alpha-authorable in the first slice.
  Future authoring requires a new stable Session-Aligned Financial Field with
  explicit report selection, scope, aggregation, revision, unit, missingness,
  and applicability semantics.
- Initial annual fields are not TTM, interim cumulative, or single-quarter
  fields. Future variants require new Field Identifiers and cannot alter or
  broaden the initial six.

### Composite Alpha and cross-sectional rank

- Composite Alpha is one ordinary Alpha Formula that combines two or more
  Numeric Series with explicit arithmetic, Builtins, signs, and literal
  weights. There is no persisted factor-list, factor-weight table, or separate
  multi-factor model.
- cs_rank accepts one Numeric Series and returns one Numeric Series. It
  evaluates independently for each Research Session inside the selected
  Liquidity Universe.
- Only finite child values participate. Missing and non-finite child values are
  excluded from the denominator and remain missing at their original
  coordinates.
- Ascending average ordinal rank is mapped to the inclusive zero-to-one range.
  Ties receive their average rank. A cross-section with exactly one valid value
  returns 0.5 for that value. A cross-section with no valid values remains all
  missing.
- cs_rank preserves its child's Effective Alpha Lookback. It does not add a
  time-series window.
- Lower-is-better semantics are expressed by explicit negation in the Formula.
  Industry Neutralization remains a configured post-expression operation over
  the complete Composite Alpha.
- The Series Execution Plan evaluates every child once, then performs rank over
  complete per-session cross-sections. ResearchRun and DailyTrack use the same
  Builtin Definition, planner, finite-number rules, and Numeric Execution
  Contract.

### ResearchRun and DailyTrack behavior

- Run admission compiles the Formula, freezes its Field References, validates
  each referenced family descriptor against the calculation slice, and stores
  the complete immutable ResearchRun input before queuing execution.
- A Formula that references financial fields cannot end after the financial
  observation-through cutoff. Market-only admission does not consult Financial
  Coverage as a gate.
- The Worker claims the queued ResearchRun, creates an Attempt, and pins the
  Data Generation descriptor frozen by admission before changing execution
  state. Opening the required data objects belongs to execution after claim,
  not to claim eligibility.
- ResearchRun evaluates the requested Research Period plus only the Effective
  Alpha Lookback required by the admitted Expression.
- DailyTrack freezes the successful seed ResearchRun input and uses the same
  Field References, Series reader, planner, Builtins, and Numeric Execution
  Contract. An advance reads only bounded lookback state plus new Research
  Sessions.
- A financial DailyTrack blocks before the first uncovered target session and
  records the family-readiness reason. It resumes only after a complete
  Financial Refresh publishes sufficient Coverage.
- Market-only DailyTracks remain eligible to advance when Financial Coverage is
  behind or Financial Refresh has failed.
- Batch-Incremental Equivalence is exact for the same sessions, universe,
  pinned family contents, Formula, and numeric contract.

### User and operator interfaces

- The Alpha Authoring Catalog exposes the six initial financial fields with
  descriptions, units, time semantics, applicability, and examples, and exposes
  cs_rank from the Builtin Catalog.
- Data Overview exposes current Market Coverage, Financial Coverage Start,
  financial observation-through cutoff, reconciliation and revision-coverage
  limitations, last successful refresh times, and Financial Research
  Readiness.
- Data Overview contains no update controls, Generation browser, raw response
  browser, company-statement explorer, or arbitrary Canonical table query.
- Market Refresh and Financial Refresh remain private operator commands with
  machine-readable progress, shard/checkpoint counts, validation failures, and
  candidate/publication outcomes.
- Failure messages distinguish source permission, rate limit, truncation,
  schema, incomplete shard, Coverage, stale-Head publication, and execution
  readiness failures without logging the TuShare token or raw sensitive
  configuration.

### Development hard cut

- The final runtime uses the family-Manifest Generation contract and selective
  Series-reading path only. The flat all-table loader is not retained as a
  compatibility path.
- The final Alpha evaluator receives Data-prepared Series and does not retain a
  prices-only branch beside the new reader.
- No schema migration, dual write, old/new endpoint pair, fallback reader,
  feature flag, or compatibility adapter is added. Development data stores and
  databases are rebuilt for the new contract.
- Intermediate candidate objects and modules may be tested before routing is
  switched, but the completed implementation removes obsolete runtime and test
  contracts rather than keeping two behaviors.

## Testing Decisions

Tests will assert externally visible behavior and domain invariants rather than
private helper calls, loop counts, or a particular internal class layout. Each
test will use the lowest layer that remains sufficiently real: pure semantic
contracts for deterministic financial and ranking rules, source replay for the
remote provider boundary, real storage and database dependencies for
Generation and Worker behavior, and one real browser journey for the product
gate. Tests use fixed calendars, instruments, UUIDs, source payloads, and
numeric expectations. They do not use public network, arbitrary sleep,
shared mutable state, or retry-to-green behavior.

### Primary product acceptance seam

The authoritative completion gate extends the existing full-stack browser
journey that currently proves one visible ResearchRun and DailyTrack. A
deterministic replay dataset is collected and published through the real Data
Operator, mounted immutable data store, database, object store, HTTP service,
Worker, and browser:

1. Bootstrap or refresh publishes a financial-capable Head with Market and
   Financial Coverage beginning in 2010.
2. Data Overview displays both family declarations and Financial Research
   Readiness without opening Parquet for the overview request.
3. The Formula editor discovers all six fields and cs_rank from the catalog.
4. A user submits one Composite Alpha containing at least one market field, one
   financial field, and cs_rank.
5. The ResearchRun is claimed, pins one Generation, succeeds, and records the
   expected provenance and deterministic results.
6. The user starts a DailyTrack from that result.
7. A later market or financial Generation is published and the Track advances
   with exact batch-incremental equality.
8. A financial Track blocks at a deliberately constructed
   financial-observation cutoff, while a market-only Track advances through the
   same market session.
9. A complete Financial Refresh advances the cutoff and the blocked financial
   Track catches up without changing its Formula or historical checkpoints.

This is one product gate rather than separate ingestion, ResearchRun, and
DailyTrack definitions of done. Failures retain browser screenshots, HTTP
payloads, run and track identities, Generation digests, and relevant service
logs.

Prior art is the existing browser test named “current data supports one visible
ResearchRun and DailyTrack journey” and the current-head ResearchRun/DailyTrack
acceptance suites. The financial flow extends that seam rather than creating a
parallel demo harness.

### Source contract seam

The TuShare adapter and Financial Refresh workflow use deterministic Stub or
Replay transports. Contract cases cover:

- ordinary per-instrument income, balance-sheet, and cash-flow responses;
- all company types, report types, date fields, nulls, duplicate rows, source
  revisions, and same-date observed corrections;
- complete-history response comparison against the selected deterministic
  date-shard union;
- permission denial, rate limiting, schema drift, response-boundary
  truncation, partial endpoint success, and exhausted retry behavior;
- checkpoint resume after process failure and idempotent replay of completed
  shards;
- full V1 refresh merging new versions while retaining old accepted versions
  no longer present upstream;
- redaction of tokens and sensitive configuration from progress and error
  logs.

The existing TuShare data-source adapter tests and Data Operator
bootstrap/refresh integration suites are the prior art. A separate live
deployment-token probe supplies operational evidence before real Bootstrap,
but live TuShare is never a CI dependency.

### Pure semantic seam

Field Catalog, point-in-time Series reading, Alpha compilation, cs_rank, and
batch/incremental execution receive exhaustive deterministic contract tests.
Cases include:

- a value published after a report period remaining invisible before its
  mapped Research Session;
- a source version changing from one amount to another and only the later
  covered sessions seeing the revision;
- an observed correction with no new source date becoming visible only after
  first observation;
- weekend and holiday announcement dates mapping through the canonical
  research calendar;
- latest-full-year selection, latest-reported balance-sheet selection, and
  minimal pre-2010 seed behavior;
- no fallback across report types, reporting scopes, company types, or missing
  source values;
- all six field definitions across company types 1 through 4;
- stable missingness when a selected instrument has no fact;
- cs_rank ascending order, ties, singleton cross-sections, all-missing
  cross-sections, non-finite values, changing Liquidity Universes, explicit
  negation, and post-expression Industry Neutralization;
- mixed market-financial Formulae and exact equality between reference batch
  results and DailyTrack advances.

The existing Alpha Expression contract tests, Alpha advance contract tests,
and DailyTrack session-coordinate integration tests are the prior art. Obsolete
prices-only expectations are replaced; they are not retained as a second Alpha
input contract.

### Storage, concurrency, and performance seam

Real immutable storage and database integration tests cover:

- one root Manifest with family descriptors and family-specific Coverage;
- content-addressed reuse of unchanged Raw Financial Batches, Parquet objects,
  and family Manifest digests;
- independent market-only and finance-only refresh publication under one Head;
- stale-Head compare-and-swap failure followed by recomposition and
  cross-family revalidation;
- an Attempt pinned to Generation A completing unchanged while a refresh
  publishes Generation B;
- garbage collection preserving every object referenced by a published
  Generation or active pin and collecting only objects with no remaining
  ownership;
- claim, pin, admission, and Data Overview reading descriptors without opening
  Parquet;
- a price-only Formula reading zero financial objects;
- a mixed Formula reading only requested family partitions and projected
  columns.

A representative 2010-scale synthetic Generation is benchmarked for cold and
warm execution. The benchmark records P50 and P95 duration, object count, bytes
read, rows scanned, and peak memory for descriptor inspection, one price-only
Formula, one financial-only Formula, and one mixed Composite Alpha. Admission
thresholds are fixed from committed representative results before the first
financial Head can publish; they are not guessed from arbitrary wall-clock
sleeps.

Prior art is the mounted Generation store suite, generation collection and
refresh integration suites, current Head lifecycle fencing tests, and the
existing Data Overview test that proves overview does not open Generation
Parquet.

### Final verification

- Deterministic unit, architecture, adapter, and integration suites pass through
  the repository's approved Python and web runtimes.
- The real database, queue, Worker, mounted data store, and object store suites
  pass in isolated environments.
- The full-stack browser acceptance passes against a fresh development stack
  with external requests rejected.
- The final production image smoke verifies schema installation, startup,
  readiness, Data Overview, Composite Alpha ResearchRun, Worker execution,
  DailyTrack start and advance, and private operator command availability.
- Failures preserve enough diagnostics to identify the source shard, family,
  Generation, Attempt, Formula, field set, and browser step without exposing
  credentials.

## Out of Scope

- TTM, single-quarter, interim cumulative, growth, per-share, profitability,
  leverage, quality, or valuation fields beyond the initial six.
- Making every retained TuShare statement column Alpha-authorable.
- TuShare fina_indicator, daily_basic, forecast, express, audit, disclosure
  schedule, announcement text, and other financial event products.
- A company financial-statement viewer, Raw Financial Batch browser, arbitrary
  Canonical query UI, downloadable statement product, or public data API.
- A separate factor-list, factor library, factor-weight resource, multi-factor
  model, or alternative Alpha editor.
- Cross-sectional z-score, winsorization, quantiles, correlation, covariance,
  regression, implicit normalization, or industry-aware ranking Builtins.
- VIP TuShare endpoints, provider switching, provider blending, runtime
  permission fallback, or Qlib/Zipline as a runtime dependency.
- Automatic Financial Refresh scheduling, recent-announcement hot windows,
  rotating historical reconciliation, or incremental source deletion in V1.
- Financial Coverage before the first Research Session of 2010 or a claim that
  TuShare exposes every historical revision ever published.
- Independently moving market and financial Heads, user-selectable Dataset
  versions, permanent retention of every old Generation, or in-place data
  mutation.
- End-user Data Refresh controls or an operations console in the ordinary
  product web interface.
- Backward-compatible flat-Generation readers, dual Alpha evaluators, schema
  migrations, data backfills between old and new contracts, fallbacks, or
  feature flags.
- Corrections to already published DailyTrack history. A later Generation
  affects later Advances and provenance; historical Tracking Checkpoints remain
  immutable.
- Public redistribution, commercial licensing, or source-attribution policy
  beyond preserving the provenance needed to make those later decisions.

## Further Notes

- This specification freezes the decisions represented by the accepted
  financial ADRs 0170, 0175, 0176, and 0178 through 0189. The obsolete
  TTM-first proposal was removed; ADR-0179 is the sole initial flow-field
  decision.
- The Alpha Language and Research Workspace specification remains the
  prerequisite for Formula compilation, stable Field References, the shared
  Series Execution Plan, and the user-visible Research workflow. Ticket
  decomposition must order those foundations before their financial consumers
  when they are not already implemented.
- Current implementation still has a flat fixed-table Generation, a
  whole-Generation opening path, a prices-only evaluator, and the old
  single-operator authoring surface. The implementation is therefore a data and
  execution contract hard cut, not a small additional source table.
- At the current local historical scope of 5,541 ordinary A-share instruments,
  one complete-history shard per three financial endpoints is approximately
  16,623 baseline source requests. The planning estimate is about 3.2 to 6.9
  hours for finance-only collection under the current serial throttle and
  representative HTTP latency assumptions.
- If Market Coverage has not already been backfilled to 2010, the first
  financial-capable Head requires roughly 33,000 or more combined market and
  financial source requests and should reserve approximately 8 to 16 hours for
  collection, mapping, object writing, and validation. These are capacity
  estimates, not service-level guarantees; the deployment capability probe and
  committed benchmark provide the implementation evidence.
- Complete Tushare source breadth is retained to avoid future recollection, but
  the product intentionally exposes only fields whose one-value-per-instrument-
  per-session semantics are fixed. Adding another field later is an additive
  data-product decision, not a switch that exposes an arbitrary retained
  column.
- Publishing this Spec does not create implementation tickets or authorize
  implementation. Ticket decomposition remains the next explicit workflow
  step.

## Comments

- Product decisions were confirmed through the preceding financial-data design
  discussion. The four testing seams were confirmed before publication. This
  file is the frozen implementation specification and is labeled
  ready-for-agent.
