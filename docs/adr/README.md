# Architecture Decision Records

This directory contains only current ThesisTrace decisions that are difficult to reverse, surprising without context, and based on a real trade-off. Product vocabulary belongs in [CONTEXT.md](../../CONTEXT.md), current topology belongs in [docs/architecture/core.md](../architecture/core.md), implementation detail belongs in code and tests, and completed work history remains in Git.

Number gaps are intentional and numbers are never reused. When a decision stops being current, merge any still-valid rationale into the surviving record, delete the obsolete file, and repair its references.

## Foundations and data semantics

- [ADR-0006 — Limit the product to end-of-day Shanghai and Shenzhen A-shares](0006-limit-to-end-of-day-shanghai-and-shenzhen-a-shares.md)
- [ADR-0009 — Use Tushare behind a source-neutral data boundary](0009-use-tushare-behind-a-source-neutral-data-boundary.md)
- [ADR-0011 — Use historical SW2021 industry classification](0011-use-historical-sw2021-industry-classification.md)
- [ADR-0012 — Separate Dataset Families by grain, time semantics, and asset](0012-separate-dataset-families-by-grain-time-semantics-and-asset.md)
- [ADR-0014 — Keep Canonical Field definitions immutable](0014-keep-canonical-field-definitions-immutable.md)
- [ADR-0016 — Apply conservative availability to date-only financial disclosures](0016-apply-conservative-availability-to-date-only-financial-disclosures.md)
- [ADR-0018 — Preserve source financial versions without inventing history](0018-preserve-source-financial-versions-without-inventing-history.md)
- [ADR-0019 — Use one minimal Instrument Identity across asset families](0019-use-one-minimal-instrument-identity-across-asset-families.md)
- [ADR-0023 — Separate Raw Market Prices from causal adjusted Research Prices](0023-separate-raw-market-prices-from-causal-cumulative-adjusted-research-prices.md)
- [ADR-0024 — Run research without Qlib](0024-run-research-without-qlib.md)
- [ADR-0025 — Value portfolios with adjusted returns without company-action events](0025-value-portfolios-with-adjusted-returns-without-company-action-events.md)
- [ADR-0026 — Align Factor labels and Strategy execution on next-open timing](0026-align-factor-labels-and-strategy-execution-on-next-open-to-open-timing.md)

## Alpha and Factor Evaluation

- [ADR-0034 — Use daily cross-sectional Rank IC as the primary Factor metric](0034-use-daily-cross-sectional-rank-ic-as-the-primary-factor-metric.md)
- [ADR-0077 — Build one Final Alpha Cross-Section before joining labels](0077-build-one-final-alpha-cross-section-before-joining-forward-labels.md)
- [ADR-0086 — Classify Forward Label unavailability without filling it](0086-classify-forward-label-unavailability-without-filling-it.md)

## Strategy execution and reporting

- [ADR-0040 — Use one long-only Top-N equal-weight Strategy](0040-use-one-long-only-top-n-equal-weight-strategy.md)
- [ADR-0042 — Use scheduled Alpha snapshots for periodic full rebalancing](0042-use-only-scheduled-alpha-snapshots-for-periodic-full-rebalancing.md)
- [ADR-0044 — Use a conservative full-fill Open Execution Model](0044-use-a-conservative-full-fill-open-execution-model.md)
- [ADR-0045 — Cancel blocked Open orders without retry or substitution](0045-cancel-blocked-open-orders-without-retry-or-substitution.md)
- [ADR-0046 — Reassess existing-position eligibility only at scheduled Rebalances](0046-reassess-existing-position-eligibility-only-at-scheduled-rebalances.md)
- [ADR-0052 — Carry the last Adjusted Research Price only for suspended-holding valuation](0052-carry-the-last-adjusted-price-only-for-suspended-holding-valuation.md)
- [ADR-0054 — Report Gross and Net NAV from one fill path](0054-report-gross-and-net-nav-from-one-fill-path.md)
- [ADR-0055 — Record Strategy NAV after each Open execution cycle](0055-record-strategy-nav-after-each-open-execution-cycle.md)
- [ADR-0070 — Use dual units for synthetic total-return accounting](0070-use-dual-units-for-synthetic-total-return-accounting.md)
- [ADR-0074 — Separate confirmed suspension from unknown market-data loss](0074-separate-confirmed-suspension-from-unknown-market-data-loss.md)
- [ADR-0081 — Use Net accounting state for all Strategy decisions](0081-use-net-accounting-state-for-all-strategy-decisions.md)
- [ADR-0089 — Use the daily first-traded price as the Open coordinate](0089-use-the-daily-first-traded-price-as-the-open-coordinate.md)
- [ADR-0100 — Resolve missing Opens from suspension and delisting evidence](0100-resolve-missing-opens-from-suspension-and-delisting-evidence.md)
- [ADR-0212 — Filter Research membership by positive-turnover observations](0212-filter-research-membership-by-positive-turnover-observations.md)
- [ADR-0231 — Use an independent append-only CSI 300 Benchmark Snapshot](0231-use-an-independent-append-only-csi-300-benchmark-snapshot.md)

## Market universe and calendar

- [ADR-0069 — Use the intersection of SSE and SZSE open days as the Research Calendar](0069-use-the-intersection-of-sse-and-szse-open-days-as-the-research-calendar.md)
- [ADR-0087 — Model historical industry membership as half-open intervals](0087-model-historical-industry-membership-as-half-open-intervals.md)
- [ADR-0090 — Keep listing lifecycle out of the Liquidity Universe](0090-keep-listing-lifecycle-out-of-the-liquidity-universe.md)
- [ADR-0097 — Build the daily Base Pool from Tushare reference evidence](0097-build-the-daily-base-pool-from-tushare-reference-evidence.md)

## Identity, access, and public entry

- [ADR-0233 — Separate Better Auth identity from Core Research authorization behind one origin](0233-separate-better-auth-identity-from-core-research-authorization.md)

## Research lifecycle, Daily Tracking, and Batches

- [ADR-0095 — Persist ResearchRun lifecycle and isolate infrastructure Attempts](0095-persist-researchrun-lifecycle-and-isolate-infrastructure-attempts.md)
- [ADR-0099 — Make one immutable Result Bundle the ResearchRun truth](0099-make-one-immutable-result-bundle-the-research-run-truth.md)
- [ADR-0103 — Start an explicit DailyTrack from a successful Strategy Backtest](0103-start-an-explicit-dailytrack-from-a-successful-strategy-backtest.md)
- [ADR-0104 — Continue DailyTrack from one fixed Tracking Origin](0104-continue-dailytrack-from-one-fixed-origin.md)
- [ADR-0105 — Publish one immutable Tracking Checkpoint per Advance](0105-publish-one-immutable-tracking-checkpoint-per-advance.md)
- [ADR-0108 — Require canonical exact Batch-Incremental Equivalence](0108-require-canonical-exact-batch-incremental-equivalence.md)
- [ADR-0109 — Pin one canonical numeric execution and serialization contract](0109-pin-one-canonical-numeric-execution-and-serialization-contract.md)
- [ADR-0214 — Select Factor Evaluation or Strategy Backtest within ResearchRun](0214-select-factor-evaluation-or-strategy-backtest-within-researchrun.md)
- [ADR-0216 — Make Research Batch a durable orchestration resource](0216-make-research-batch-a-durable-orchestration-resource.md)

## Core runtime, storage, and data lifecycle

- [ADR-0122 — Block publication on invariant failure, not statistical drift](0122-block-publication-on-invariant-failure-not-statistical-drift.md)
- [ADR-0131 — Preserve complete Liquidity Universes with bounded-memory columnar execution](0131-preserve-complete-liquidity-universes-with-bounded-memory-columnar-execution.md)
- [ADR-0146 — Store growing tabular data as partitioned Parquet](0146-store-growing-tabular-data-as-partitioned-parquet.md)
- [ADR-0151 — Make module-first Core the only active runtime](0151-make-module-first-core-the-only-active-runtime.md)
- [ADR-0152 — Use one full Compose topology for local Development and Test](0152-use-one-full-compose-topology-for-local-development-and-test.md)
- [ADR-0153 — Use user-selected Research Periods and derived Alpha warm-up](0153-use-user-selected-research-periods-and-derived-alpha-warm-up.md)
- [ADR-0154 — Use a mounted current Dataset Head and temporary Data Generations](0154-use-a-mounted-current-dataset-head-and-temporary-data-generations.md)
- [ADR-0155 — Refresh market data through a private operator overlap merge](0155-refresh-market-data-through-a-private-operator-overlap-merge.md)

## Agent access

- [ADR-0220 — Expose Research Agent access through a native Core MCP adapter](0220-expose-research-agent-access-through-a-native-core-mcp-adapter.md)
- [ADR-0221 — Authenticate remote Research Agent access with OAuth](0221-authenticate-remote-research-agent-access-with-oauth.md)
- [ADR-0222 — Keep Research Agent execution stateless and resource-addressed](0222-keep-research-agent-execution-stateless-and-resource-addressed.md)
- [ADR-0223 — Separate dangerous Research Agent authority from human confirmation](0223-separate-dangerous-research-agent-authority-from-human-confirmation.md)

## Alpha language and authoring

- [ADR-0157 — Compile Alpha Formulas when a Run is admitted](0157-compile-alpha-formulas-when-a-run-is-admitted.md)
- [ADR-0158 — Separate Alpha Field and Builtin ownership](0158-separate-alpha-field-and-builtin-ownership.md)
- [ADR-0159 — Keep one current Alpha Language with hard cuts](0159-keep-one-current-alpha-language-with-hard-cuts.md)
- [ADR-0160 — Use a small static Alpha value model](0160-use-a-small-static-alpha-value-model.md)
- [ADR-0164 — Evaluate Alpha as a Series execution plan](0164-evaluate-alpha-as-a-series-execution-plan.md)
- [ADR-0166 — Make the backend Alpha Compiler the diagnostic authority](0166-make-the-backend-alpha-compiler-the-diagnostic-authority.md)
- [ADR-0167 — Parse Formulae with a strict Python AST subset](0167-parse-formulas-with-a-strict-python-ast-subset.md)
- [ADR-0169 — Require an explicit Data-owned Alpha Field Capability](0169-require-an-explicit-data-owned-alpha-field-capability.md)
- [ADR-0191 — Separate authoring identifiers from Canonical Field References](0191-separate-authoring-identifiers-from-canonical-field-references.md)

## Research organization

- [ADR-0171 — Organize Runs in one-level Research Folders](0171-organize-runs-in-one-level-research-folders.md)
- [ADR-0172 — Separate Research organization from immutable Run input](0172-separate-research-organization-from-run-input.md)
- [ADR-0173 — Delete only terminal Research without cascading Tracks](0173-delete-only-terminal-research-without-cascading-tracks.md)
- [ADR-0174 — Delete only stopped DailyTracks](0174-delete-only-stopped-dailytracks.md)

## Financial data

- [ADR-0170 — Preserve complete financial source data but author only session-aligned fields](0170-preserve-complete-financial-source-data-but-author-only-session-aligned-fields.md)
- [ADR-0175 — Store each financial statement kind as a wide version table](0175-store-each-financial-statement-kind-as-a-wide-version-table.md)
- [ADR-0176 — Ingest all financial company types with explicit Field applicability](0176-ingest-all-financial-company-types-with-explicit-field-applicability.md)
- [ADR-0178 — Use consolidated statements for the six financial fields](0178-use-consolidated-statements-for-the-six-financial-fields.md)
- [ADR-0179 — Use latest annual flow fields and latest reported stock fields](0179-use-latest-annual-flow-fields-and-latest-reported-stock-fields.md)
- [ADR-0180 — Use per-instrument Tushare financial collection](0180-use-per-instrument-tushare-financial-collection.md)
- [ADR-0181 — Refresh Market and Financial Families independently under one Head](0181-refresh-market-and-financial-families-independently-under-one-head.md)
- [ADR-0183 — Give each Dataset Family its own Coverage declaration](0183-give-each-dataset-family-its-own-coverage-declaration.md)
- [ADR-0184 — Start Financial Coverage in 2010 with minimal pre-start seeds](0184-start-financial-coverage-in-2010-with-minimal-pre-start-seeds.md)
- [ADR-0188 — Expose financial data only through Alpha authoring and Data readiness](0188-expose-financial-data-only-through-alpha-authoring-and-data-readiness.md)
- [ADR-0192 — Paginate the ordinary balance sheet inside one logical shard](0192-paginate-the-ordinary-balance-sheet-inside-one-logical-shard.md)
- [ADR-0219 — Drive daily financial refresh from CNINFO disclosures](0219-drive-daily-financial-refresh-from-cninfo-disclosures.md)
- [ADR-0232 — Resolve financial announcement triggers from stock-level Canonical deltas](0232-resolve-financial-announcement-triggers-from-stock-level-canonical-deltas.md)

## Bounded execution and operations

- [ADR-0190 — Freeze the Data Generation at ResearchRun admission](0190-freeze-data-generation-at-researchrun-admission.md)
- [ADR-0194 — Admit long Research by peak execution footprint](0194-admit-long-research-by-peak-execution-footprint.md)
- [ADR-0195 — Resume infrastructure retries from private ResearchRun Checkpoints](0195-resume-infrastructure-retries-from-private-researchrun-checkpoints.md)
- [ADR-0198 — Make ResearchRun cancellation cooperative and confirmed](0198-make-researchrun-cancellation-cooperative-and-confirmed.md)
- [ADR-0200 — Use PyArrow and NumPy as the single columnar Research backend](0200-use-pyarrow-and-numpy-as-the-single-columnar-research-backend.md)
- [ADR-0201 — Scale Research concurrency with single-slot Workers](0201-scale-research-concurrency-with-single-slot-workers.md)
- [ADR-0202 — Claim ResearchRuns in strict FIFO order](0202-claim-researchruns-in-strict-fifo-order.md)
- [ADR-0206 — Retry only transient ResearchRun infrastructure failures](0206-retry-only-transient-researchrun-infrastructure-failures.md)
- [ADR-0209 — Recompute failed Tracking Advances from the authoritative Head](0209-recompute-failed-tracking-advances-from-the-authoritative-head.md)
- [ADR-0210 — Confirm DailyTrack Stop after the execution child exits](0210-confirm-dailytrack-stop-after-the-execution-child-exits.md)
- [ADR-0211 — Hard-cut result-changing calculation contracts](0211-hard-cut-result-changing-calculation-contracts.md)
- [ADR-0217 — Keep operational telemetry diagnostic and Product State authoritative](0217-keep-operational-telemetry-diagnostic-and-product-state-authoritative.md)
- [ADR-0218 — Separate ordinary Research, Batch Research, and Tracking Worker pools](0218-separate-ordinary-batch-research-and-tracking-worker-pools.md)
