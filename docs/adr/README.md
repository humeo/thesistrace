# Architecture Decision Records

This directory is the current accepted decision set for ThesisTrace. It
is not a specification or a second glossary: product language belongs in
[`CONTEXT.md`](../../CONTEXT.md), current topology belongs in
[`docs/architecture/core.md`](../architecture/core.md), and implementation
acceptance belongs in tests and the local issue tracker.

## Reading the record

- Read the smallest relevant group below, then follow explicit ADR references.
- Every indexed ADR is current and uses the active domain language.
- Number gaps are intentional. Removed product directions remain recoverable in
  Git history; numbers are never reused.

## Decision gate

Add an ADR only when the decision is all three of the following:

1. Hard to reverse.
2. Surprising without its context.
3. The result of a real trade-off.

Keep the record focused on the decision and why it was chosen. Formulas,
parameter lists, UI copy, task history, and implementation walkthroughs belong
in their authoritative specification, tests, runbook, or architecture document.
Never renumber or reuse an ADR number. When a later decision fully replaces one,
merge any still-current rationale into the surviving decision, delete the old
file, and rely on Git for history. When only implementation facts change, update
their real authority instead of adding an ADR.

## Foundations and data semantics

- [ADR-0006 — Limit V1 to end-of-day Shanghai and Shenzhen A-shares](0006-limit-v1-to-end-of-day-shanghai-and-shenzhen-a-shares.md)
- [ADR-0009 — Use Tushare behind a source-neutral data boundary](0009-use-tushare-behind-a-source-neutral-data-boundary.md)
- [ADR-0010 — Rank V1 liquidity universes by 20-session average turnover amount](0010-rank-v1-liquidity-universes-by-20-session-average-turnover-amount.md)
- [ADR-0011 — Use historical SW2021 industry classification](0011-use-historical-sw2021-industry-classification.md)
- [ADR-0012 — Separate Dataset Families by grain, time semantics, and asset](0012-separate-dataset-families-by-grain-time-semantics-and-asset.md)
- [ADR-0014 — Keep Canonical Market Data field definitions immutable](0014-keep-canonical-field-definitions-immutable.md)
- [ADR-0016 — Apply conservative availability to date-only financial disclosures](0016-apply-conservative-availability-to-date-only-financial-disclosures.md)
- [ADR-0018 — Preserve source financial versions without inventing history](0018-preserve-source-financial-versions-without-inventing-history.md)
- [ADR-0019 — Use one minimal Instrument Identity across asset families](0019-use-one-minimal-instrument-identity-across-asset-families.md)
- [ADR-0022 — Use the selected Liquidity Universe as the Strategy Benchmark](0022-use-the-selected-liquidity-universe-as-the-strategy-benchmark.md)
- [ADR-0023 — Separate Raw Market Prices from causal cumulative-adjusted Research Prices](0023-separate-raw-market-prices-from-causal-cumulative-adjusted-research-prices.md)
- [ADR-0024 — Run V1 research without Qlib](0024-run-v1-research-without-qlib.md)
- [ADR-0025 — Value V1 portfolios with adjusted returns without company-action events](0025-value-v1-portfolios-with-adjusted-returns-without-company-action-events.md)
- [ADR-0026 — Align Factor labels and Strategy execution on next-open-to-open timing](0026-align-factor-labels-and-strategy-execution-on-next-open-to-open-timing.md)

## Alpha and factor evaluation

- [ADR-0029 — Cap Effective Alpha Lookback at 252 market sessions](0029-cap-effective-alpha-lookback-at-252-market-sessions.md)
- [ADR-0030 — Propagate missing and invalid Alpha inputs strictly](0030-propagate-missing-and-invalid-alpha-inputs-strictly.md)
- [ADR-0031 — Do not winsorize or standardize V1 Alpha Values](0031-do-not-winsorize-or-standardize-v1-alpha-values.md)
- [ADR-0032 — Give higher Alpha Values one fixed bullish direction](0032-give-higher-alpha-values-one-fixed-bullish-direction.md)
- [ADR-0033 — Evaluate every V1 Alpha at one, five, and twenty-session horizons](0033-evaluate-every-v1-alpha-at-one-five-and-twenty-session-horizons.md)
- [ADR-0034 — Use daily cross-sectional Rank IC as the primary Factor metric](0034-use-daily-cross-sectional-rank-ic-as-the-primary-factor-metric.md)
- [ADR-0036 — Require thirty valid pairs for a daily Factor correlation](0036-require-thirty-valid-pairs-for-a-daily-factor-correlation.md)
- [ADR-0037 — Add five Alpha quantiles and Top-Bottom return to Factor Evaluation](0037-add-five-alpha-quantiles-and-top-bottom-return-to-factor-evaluation.md)
- [ADR-0038 — Keep equal Alpha Values in the same Factor quantile](0038-keep-equal-alpha-values-in-the-same-factor-quantile.md)
- [ADR-0077 — Build one final Alpha cross-section before joining forward labels](0077-build-one-final-alpha-cross-section-before-joining-forward-labels.md)
- [ADR-0082 — Require literal one-to-252 Alpha window arguments](0082-require-literal-one-to-252-alpha-window-arguments.md)
- [ADR-0083 — Use one float64 Alpha numeric contract](0083-use-one-float64-alpha-numeric-contract.md)
- [ADR-0084 — Use standard Spearman semantics for Rank IC](0084-use-standard-spearman-semantics-for-rank-ic.md)
- [ADR-0085 — Assign Factor quantiles from average Alpha rank](0085-assign-factor-quantiles-from-average-alpha-rank.md)
- [ADR-0086 — Classify Forward Label unavailability without filling it](0086-classify-forward-label-unavailability-without-filling-it.md)
- [ADR-0093 — Require thirty valid pairs for Five-Quantile analysis](0093-require-thirty-valid-pairs-for-five-quantile-analysis.md)

## Strategy execution and reporting

- [ADR-0039 — Exclude point-in-time ST stocks from V1 Research Eligibility](0039-exclude-point-in-time-st-stocks-from-v1-research-eligibility.md)
- [ADR-0040 — Limit V1 to one long-only Top-N equal-weight Strategy](0040-limit-v1-to-one-long-only-top-n-equal-weight-strategy.md)
- [ADR-0041 — Require an explicit Holdings Count capped at one hundred](0041-require-an-explicit-holdings-count-capped-at-one-hundred.md)
- [ADR-0042 — Use only scheduled Alpha snapshots for periodic full rebalancing](0042-use-only-scheduled-alpha-snapshots-for-periodic-full-rebalancing.md)
- [ADR-0043 — Require a one-to-twenty-session Rebalance Interval](0043-require-a-one-to-twenty-session-rebalance-interval.md)
- [ADR-0044 — Use a conservative full-fill open execution model](0044-use-a-conservative-full-fill-open-execution-model.md)
- [ADR-0045 — Cancel blocked open orders without retry or substitution](0045-cancel-blocked-open-orders-without-retry-or-substitution.md)
- [ADR-0046 — Reassess existing-position eligibility only at scheduled Rebalances](0046-reassess-existing-position-eligibility-only-at-scheduled-rebalances.md)
- [ADR-0047 — Fix and record V1 Initial Cash at ten million CNY](0047-fix-and-record-v1-initial-cash-at-ten-million-cny.md)
- [ADR-0048 — Sell before buying target deficits in Alpha order](0048-sell-before-buying-target-deficits-in-alpha-order.md)
- [ADR-0049 — Apply board-specific A-share order-quantity rules](0049-apply-board-specific-a-share-order-quantity-rules.md)
- [ADR-0050 — Use one explicit all-in V1 Transaction Cost model](0050-use-one-explicit-all-in-v1-transaction-cost-model.md)
- [ADR-0051 — Split logical orders at board-specific single-order limits](0051-split-logical-orders-at-board-specific-single-order-limits.md)
- [ADR-0052 — Carry the last Adjusted Research Price only for suspended-holding valuation](0052-carry-the-last-adjusted-price-only-for-suspended-holding-valuation.md)
- [ADR-0053 — Keep suspended members in the equal-weight Strategy Benchmark](0053-keep-suspended-members-in-the-equal-weight-strategy-benchmark.md)
- [ADR-0054 — Report Gross and Net NAV from one fill path](0054-report-gross-and-net-nav-from-one-fill-path.md)
- [ADR-0055 — Record Strategy NAV after each open execution cycle](0055-record-strategy-nav-after-each-open-execution-cycle.md)
- [ADR-0056 — Report Net-primary cumulative return and trading-day CAGR](0056-report-net-primary-cumulative-return-and-trading-day-cagr.md)
- [ADR-0057 — Calculate Annualized Excess Return from relative Net wealth](0057-calculate-annualized-excess-from-relative-net-wealth.md)
- [ADR-0058 — Calculate Maximum Drawdown from Net NAV](0058-calculate-maximum-drawdown-from-net-nav.md)
- [ADR-0059 — Annualize sample volatility of daily Net Returns](0059-annualize-sample-volatility-of-daily-net-returns.md)
- [ADR-0060 — Calculate Net Return Sharpe with zero risk-free rate](0060-calculate-net-return-sharpe-with-zero-risk-free-rate.md)
- [ADR-0061 — Calculate Calmar from Net CAGR and Maximum Drawdown](0061-calculate-calmar-from-net-cagr-and-maximum-drawdown.md)
- [ADR-0062 — Report Turnover as one event series and two aggregates](0062-report-turnover-as-one-event-series-and-two-aggregates.md)
- [ADR-0063 — Report cost amount, ratio, and Cumulative Return drag](0063-report-cost-amount-ratio-and-cumulative-return-drag.md)
- [ADR-0064 — Report daily Actual Holdings Count and four aggregates](0064-report-daily-actual-holdings-count-and-four-aggregates.md)
- [ADR-0065 — Report actual Maximum Single-Name Weight without enforcing a cap](0065-report-actual-maximum-single-name-weight-without-enforcing-a-cap.md)
- [ADR-0066 — Report daily actual Cash Ratio and three aggregates](0066-report-daily-actual-cash-ratio-and-three-aggregates.md)
- [ADR-0067 — Separate three market-rejection counts from other execution diagnostics](0067-separate-three-market-rejection-counts-from-other-execution-diagnostics.md)
- [ADR-0070 — Use dual units for synthetic total-return accounting](0070-use-dual-units-for-synthetic-total-return-accounting.md)
- [ADR-0074 — Separate confirmed suspension from unknown market-data loss](0074-separate-confirmed-suspension-from-unknown-market-data-loss.md)
- [ADR-0078 — Break Strategy Alpha ties by instrument identity](0078-break-strategy-alpha-ties-by-instrument-identity.md)
- [ADR-0081 — Use Net accounting state for all Strategy decisions](0081-use-net-accounting-state-for-all-strategy-decisions.md)
- [ADR-0089 — Use the daily first-traded price as the Open coordinate](0089-use-the-daily-first-traded-price-as-the-open-coordinate.md)
- [ADR-0094 — Calculate Transaction Costs without per-order cent rounding](0094-calculate-transaction-costs-without-per-order-cent-rounding.md)
- [ADR-0100 — Resolve a held position's missing Open by short-circuiting to suspension then delisting](0100-resolve-a-held-positions-missing-open-by-short-circuiting-to-suspension-then-delisting.md)
- [ADR-0101 — Resolve missing Benchmark and Label Opens on demand for terminal delisting](0101-resolve-missing-benchmark-and-label-opens-on-demand-for-terminal-delisting.md)

## Market universe and calendar

- [ADR-0069 — Use the intersection of SSE and SZSE open days as the Research Calendar](0069-use-the-intersection-of-sse-and-szse-open-days-as-the-research-calendar.md)
- [ADR-0071 — Standardize all eleven V1 Tushare daily fields](0071-standardize-all-eleven-v1-tushare-daily-fields.md)
- [ADR-0075 — Limit V1 universes to ordinary SSE and SZSE A-shares](0075-limit-v1-universes-to-ordinary-sse-and-szse-a-shares.md)
- [ADR-0076 — Break liquidity-score ties by instrument identity](0076-break-liquidity-score-ties-by-instrument-identity.md)
- [ADR-0087 — Model historical industry membership as half-open intervals](0087-model-historical-industry-membership-as-half-open-intervals.md)
- [ADR-0090 — Keep listing lifecycle out of the Liquidity Universe](0090-keep-listing-lifecycle-out-of-the-liquidity-universe.md)
- [ADR-0097 — Build the daily Base Pool from Tushare reference evidence](0097-build-the-daily-base-pool-from-tushare-reference-evidence.md)

## Research lifecycle and daily tracking

- [ADR-0095 — Give each ResearchRun a persistent terminal state and attempts](0095-give-each-research-run-a-persistent-terminal-state-and-attempts.md)
- [ADR-0099 — Make one immutable Result Bundle the ResearchRun truth](0099-make-one-immutable-result-bundle-the-research-run-truth.md)
- [ADR-0102 — Make batch-versus-incremental equivalence the V1 end-to-end goal](0102-make-batch-versus-incremental-equivalence-the-v1-end-to-end-goal.md)
- [ADR-0103 — Start an explicit DailyTrack from a successful ResearchRun](0103-start-an-explicit-daily-track-from-a-successful-research-run.md)
- [ADR-0104 — Continue DailyTrack from one fixed Tracking Origin](0104-continue-daily-track-from-one-fixed-origin.md)
- [ADR-0105 — Publish one immutable Tracking Checkpoint per Advance](0105-publish-one-immutable-tracking-checkpoint-per-advance.md)
- [ADR-0108 — Require canonical exact Batch-Incremental Equivalence](0108-require-canonical-exact-batch-incremental-equivalence.md)
- [ADR-0109 — Pin one canonical numeric execution and serialization contract](0109-pin-one-canonical-numeric-execution-and-serialization-contract.md)
- [ADR-0216 — Make Research Batch a durable orchestration resource](0216-make-research-batch-a-durable-orchestration-resource.md)

## Core runtime, storage, and data lifecycle

- [ADR-0122 — Block publication on invariant failure, not statistical drift](0122-block-publication-on-invariant-failure-not-statistical-drift.md)
- [ADR-0131 — Preserve Top 3000 with bounded-memory columnar execution](0131-preserve-top-3000-with-bounded-memory-columnar-execution.md)
- [ADR-0146 — Store growing tabular data as partitioned Parquet](0146-store-growing-tabular-data-as-partitioned-parquet.md)
- [ADR-0151 — Make module-first Core the only active runtime](0151-make-module-first-core-the-only-active-runtime.md)
- [ADR-0152 — Use one full Compose topology for local Development and Test](0152-use-one-full-compose-topology-for-local-development-and-test.md)
- [ADR-0153 — Use user-selected Research Periods and derived Alpha warm-up](0153-use-user-selected-research-periods-and-derived-alpha-warm-up.md)
- [ADR-0154 — Use a mounted current Dataset Head and temporary Data Generations](0154-use-a-mounted-current-dataset-head-and-temporary-data-generations.md)
- [ADR-0155 — Refresh market data through a private operator overlap merge](0155-refresh-market-data-through-a-private-operator-overlap-merge.md)

## Alpha language and authoring

- [ADR-0157 — Compile Alpha Formulas when a Run is admitted](0157-compile-alpha-formulas-when-a-run-is-admitted.md)
- [ADR-0158 — Separate Alpha field and builtin ownership](0158-separate-alpha-field-and-builtin-ownership.md)
- [ADR-0159 — Keep one current Alpha Language with hard cuts](0159-keep-one-current-alpha-language-with-hard-cuts.md)
- [ADR-0160 — Use a small static Alpha value model](0160-use-a-small-static-alpha-value-model.md)
- [ADR-0161 — Use one bare-identifier Alpha expression](0161-use-one-bare-identifier-alpha-expression.md)
- [ADR-0162 — Use one global Alpha Identifier namespace](0162-use-one-global-alpha-identifier-namespace.md)
- [ADR-0163 — Make each Alpha Builtin one self-contained definition](0163-make-each-alpha-builtin-one-self-contained-definition.md)
- [ADR-0164 — Evaluate Alpha as a Series execution plan](0164-evaluate-alpha-as-a-series-execution-plan.md)
- [ADR-0166 — Make the backend Alpha Compiler the diagnostic authority](0166-make-the-backend-alpha-compiler-the-diagnostic-authority.md)
- [ADR-0167 — Parse Formulae with a strict Python AST subset](0167-parse-formulas-with-a-strict-python-ast-subset.md)
- [ADR-0168 — Make the DSL editor the only Alpha authoring surface](0168-make-the-dsl-editor-the-only-alpha-authoring-surface.md)
- [ADR-0169 — Require an explicit Data-owned Alpha Field Capability](0169-require-an-explicit-data-owned-alpha-field-capability.md)
- [ADR-0189 — Add one cross-sectional rank Builtin for Composite Alpha](0189-add-one-cross-sectional-rank-builtin-for-composite-alpha.md)
- [ADR-0191 — Separate Alpha identifiers from namespaced Field References](0191-separate-alpha-identifiers-from-namespaced-field-references.md)
- [ADR-0215 — Use domain names for Alpha Identifiers](0215-use-domain-names-for-alpha-identifiers.md)

## Research organization

- [ADR-0171 — Organize Runs in one-level Research Folders](0171-organize-runs-in-one-level-research-folders.md)
- [ADR-0172 — Separate Research organization from immutable Run input](0172-separate-research-organization-from-run-input.md)
- [ADR-0173 — Delete only terminal Research without cascading Tracks](0173-delete-only-terminal-research-without-cascading-tracks.md)
- [ADR-0174 — Delete only stopped DailyTracks](0174-delete-only-stopped-daily-tracks.md)

## Financial data

- [ADR-0170 — Preserve complete financial source data but author only session-aligned fields](0170-preserve-complete-financial-source-data-but-author-only-session-aligned-fields.md)
- [ADR-0175 — Store each financial statement kind as a wide version table](0175-store-each-financial-statement-kind-as-a-wide-version-table.md)
- [ADR-0176 — Ingest all financial company types but author fields with explicit applicability](0176-ingest-all-financial-company-types-but-author-fields-with-explicit-applicability.md)
- [ADR-0178 — Use consolidated statements for the six financial fields](0178-use-consolidated-statements-for-the-six-financial-fields.md)
- [ADR-0179 — Use latest annual flow fields and latest reported stock fields](0179-use-latest-annual-flow-fields-and-latest-reported-stock-fields.md)
- [ADR-0180 — Use one ordinary per-instrument Tushare financial collector](0180-use-one-ordinary-per-instrument-tushare-financial-collector.md)
- [ADR-0181 — Refresh market and financial families independently under one Head](0181-refresh-market-and-financial-families-independently-under-one-head.md)
- [ADR-0183 — Give each Dataset Family its own Coverage declaration](0183-give-each-dataset-family-its-own-coverage-declaration.md)
- [ADR-0184 — Start Financial Coverage in 2010 with minimal pre-start seeds](0184-start-financial-coverage-in-2010-with-minimal-pre-start-seeds.md)
- [ADR-0185 — Rebuild the complete financial family on every V1 refresh](0185-rebuild-the-complete-financial-family-on-every-v1-refresh.md)
- [ADR-0186 — Apply the six financial fields to all company types](0186-apply-the-six-financial-fields-to-all-company-types.md)
- [ADR-0188 — Expose financial data only through Alpha authoring and Data readiness](0188-expose-financial-data-only-through-alpha-authoring-and-data-readiness.md)
- [ADR-0192 — Paginate the ordinary balance sheet inside one logical shard](0192-paginate-the-ordinary-balance-sheet-inside-one-logical-shard.md)

## Bounded execution and operations

- [ADR-0190 — Freeze the Data Generation at ResearchRun admission](0190-freeze-data-generation-at-research-run-admission.md)
- [ADR-0193 — Checkpoint each complete Tushare market session](0193-checkpoint-each-tushare-market-session.md)
- [ADR-0194 — Admit long Research by peak execution footprint, not total work](0194-admit-long-research-by-peak-execution-footprint.md)
- [ADR-0195 — Resume infrastructure retries from private ResearchRun checkpoints](0195-resume-infrastructure-retries-from-private-researchrun-checkpoints.md)
- [ADR-0196 — Execute ResearchRun in contiguous full-Universe session chunks](0196-execute-researchrun-in-contiguous-full-universe-session-chunks.md)
- [ADR-0197 — Carry only bounded continuation state between ResearchRun chunks](0197-carry-only-bounded-continuation-state-between-researchrun-chunks.md)
- [ADR-0198 — Make ResearchRun cancellation cooperative and confirmed](0198-make-researchrun-cancellation-cooperative-and-confirmed.md)
- [ADR-0199 — Report ResearchRun progress from committed chunks](0199-report-researchrun-progress-from-committed-chunks.md)
- [ADR-0200 — Use PyArrow and NumPy as the single columnar Research backend](0200-use-pyarrow-and-numpy-as-the-single-columnar-research-backend.md)
- [ADR-0201 — Scale Research concurrency with single-slot Workers](0201-scale-research-concurrency-with-single-slot-workers.md)
- [ADR-0202 — Claim ResearchRuns in strict FIFO order](0202-claim-researchruns-in-strict-fifo-order.md)
- [ADR-0206 — Retry only transient ResearchRun infrastructure failures](0206-retry-only-transient-researchrun-infrastructure-failures.md)
- [ADR-0207 — Reset development Product State without erasing Canonical Data](0207-reset-development-product-state-without-erasing-canonical-data.md)
- [ADR-0218 — Separate ordinary Research, Batch Research, and Tracking Worker pools](0218-separate-ordinary-batch-research-and-tracking-worker-pools.md)
- [ADR-0209 — Recompute failed Tracking Advances from the authoritative Head](0209-recompute-failed-tracking-advances-from-the-authoritative-head.md)
- [ADR-0210 — Confirm DailyTrack Stop after the execution child exits](0210-confirm-dailytrack-stop-after-the-execution-child-exits.md)
- [ADR-0211 — Hard-cut result-changing calculation contracts](0211-hard-cut-result-changing-calculation-contracts.md)
- [ADR-0212 — Filter Research membership by positive-turnover observations](0212-filter-research-membership-by-positive-turnover-observations.md)
- [ADR-0214 — Select Factor Evaluation or Strategy Backtest within ResearchRun](0214-select-factor-evaluation-or-strategy-backtest-within-researchrun.md)
