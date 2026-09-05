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
- [ADR-0019 — Use one Instrument Identity across Canonical families](0019-use-one-instrument-identity-across-canonical-families.md)
- [ADR-0023 — Separate Raw Market Prices from causal adjusted Research Prices](0023-separate-raw-market-prices-from-causal-cumulative-adjusted-research-prices.md)
- [ADR-0024 — Run research without Qlib](0024-run-research-without-qlib.md)
- [ADR-0026 — Align Factor labels and Strategy execution on next-open timing](0026-align-factor-labels-and-strategy-execution-on-next-open-to-open-timing.md)
- [ADR-0070 — Use dual units for synthetic total-return accounting](0070-use-dual-units-for-synthetic-total-return-accounting.md)

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
- [ADR-0054 — Report Gross and Net NAV from one fill path](0054-report-gross-and-net-nav-from-one-fill-path.md)
- [ADR-0055 — Record Strategy NAV after each Open execution cycle](0055-record-strategy-nav-after-each-open-execution-cycle.md)
- [ADR-0074 — Separate confirmed suspension from unknown market-data loss](0074-separate-confirmed-suspension-from-unknown-market-data-loss.md)
- [ADR-0089 — Use the daily first-traded price as the Open coordinate](0089-use-the-daily-first-traded-price-as-the-open-coordinate.md)
- [ADR-0100 — Resolve missing Opens from suspension and delisting evidence](0100-resolve-missing-opens-from-suspension-and-delisting-evidence.md)
- [ADR-0212 — Filter Research membership by positive-turnover observations](0212-filter-research-membership-by-positive-turnover-observations.md)
- [ADR-0231 — Use an independent append-only CSI 300 Benchmark Snapshot](0231-use-an-independent-append-only-csi-300-benchmark-snapshot.md)

## Market universe and calendar

- [ADR-0069 — Use the intersection of SSE and SZSE open days as the Research Calendar](0069-use-the-intersection-of-sse-and-szse-open-days-as-the-research-calendar.md)
- [ADR-0097 — Build the daily Base Pool from Tushare reference evidence](0097-build-the-daily-base-pool-from-tushare-reference-evidence.md)

## Identity, access, and public entry

- [ADR-0233 — Separate Better Auth identity from Core Research authorization](0233-separate-better-auth-identity-from-core-research-authorization.md)
- [ADR-0239 — Grant one Operator capability without general RBAC](0239-expose-one-capability-gated-operator-console.md)
- [ADR-0241 — Keep Operator authority split between Auth and Core](0241-keep-operator-authority-split-between-auth-and-core.md)

## Research lifecycle, Daily Tracking, and Batches

- [ADR-0095 — Persist ResearchRun lifecycle and isolate infrastructure Attempts](0095-persist-researchrun-lifecycle-and-isolate-infrastructure-attempts.md)
- [ADR-0099 — Make one immutable Result Bundle the ResearchRun truth](0099-make-one-immutable-result-bundle-the-research-run-truth.md)
- [ADR-0103 — Start an explicit DailyTrack from a successful Strategy Backtest](0103-start-an-explicit-dailytrack-from-a-successful-strategy-backtest.md)
- [ADR-0104 — Continue DailyTrack from one fixed Tracking Origin](0104-continue-dailytrack-from-one-fixed-origin.md)
- [ADR-0105 — Publish one immutable Tracking Checkpoint per Advance](0105-publish-one-immutable-tracking-checkpoint-per-advance.md)
- [ADR-0108 — Require canonical exact Batch-Incremental Equivalence](0108-require-canonical-exact-batch-incremental-equivalence.md)
- [ADR-0109 — Pin one canonical numeric execution and serialization contract](0109-pin-one-canonical-numeric-execution-and-serialization-contract.md)
- [ADR-0214 — Select Factor Evaluation or Strategy Backtest within ResearchRun](0214-select-factor-evaluation-or-strategy-backtest-within-researchrun.md)
- [ADR-0216 — Share bounded Batch calculation and recover complete tasks](0216-share-bounded-batch-calculation-and-recover-complete-tasks.md)
- [ADR-0234 — Require explicit DailyTrack Refresh](0234-require-explicit-dailytrack-refresh.md)

## Core runtime, storage, and data lifecycle

- [ADR-0146 — Store Canonical and analytical tables as partitioned Parquet](0146-store-canonical-and-analytical-tables-as-partitioned-parquet.md)
- [ADR-0151 — Keep research authority inside a module-first Core](0151-keep-research-authority-inside-a-module-first-core.md)
- [ADR-0152 — Use one full Compose topology for local Development and Test](0152-use-one-full-compose-topology-for-local-development-and-test.md)
- [ADR-0153 — Use user-selected Research Periods and derived Alpha warm-up](0153-use-user-selected-research-periods-and-derived-alpha-warm-up.md)
- [ADR-0154 — Use a mounted current Dataset Head and temporary Data Generations](0154-use-a-mounted-current-dataset-head-and-temporary-data-generations.md)
- [ADR-0155 — Refresh market data by validating an overlap merge](0155-refresh-market-data-by-validating-an-overlap-merge.md)
- [ADR-0194 — Admit complete research by bounded execution footprint](0194-admit-long-research-by-peak-execution-footprint.md)
- [ADR-0240 — Run Data Refresh through one durable Operator Worker](0240-run-data-refresh-through-one-durable-operator-worker.md)

## Agent access

- [ADR-0220 — Expose Research Agent access through a native Core MCP adapter](0220-expose-research-agent-access-through-a-native-core-mcp-adapter.md)
- [ADR-0221 — Authorize remote Research Agents by Researcher and scope](0221-authenticate-remote-research-agent-access-with-oauth.md)
- [ADR-0222 — Keep Research Agent execution stateless and resource-addressed](0222-keep-research-agent-execution-stateless-and-resource-addressed.md)
- [ADR-0223 — Separate dangerous Research Agent authority from human confirmation](0223-separate-dangerous-research-agent-authority-from-human-confirmation.md)
- [ADR-0235 — Run the built-in Research Agent in a separate Host](0235-run-the-built-in-research-agent-in-a-separate-host.md)
- [ADR-0236 — Keep Agent Chat separate from Research truth](0236-keep-agent-chat-separate-from-research-truth.md)
- [ADR-0237 — Exchange Login Sessions for short-lived MCP tokens in Auth](0237-exchange-login-sessions-for-short-lived-mcp-tokens-in-auth.md)
- [ADR-0238 — Keep Agent content out of operational telemetry](0238-keep-agent-content-out-of-operational-telemetry.md)
- [ADR-0242 — Own external MCP authorization and revocation in Auth](0242-own-external-mcp-authorization-in-auth.md)

## Alpha language and authoring

- [ADR-0157 — Compile and validate Alpha Formulas at ResearchRun admission](0157-compile-alpha-formulas-when-a-run-is-admitted.md)
- [ADR-0158 — Keep Alpha field authority in Data and operation authority in the Kernel](0158-separate-alpha-field-and-builtin-ownership.md)
- [ADR-0160 — Use a small static Alpha value model](0160-use-a-small-static-alpha-value-model.md)
- [ADR-0164 — Evaluate Alpha as a Series execution plan](0164-evaluate-alpha-as-a-series-execution-plan.md)
- [ADR-0167 — Parse Formulae with a strict Python AST subset](0167-parse-formulas-with-a-strict-python-ast-subset.md)
- [ADR-0191 — Separate authoring identifiers from Canonical Field References](0191-separate-authoring-identifiers-from-canonical-field-references.md)
- [ADR-0211 — Execute only the current Alpha and calculation contracts](0211-hard-cut-result-changing-calculation-contracts.md)

## Research organization

- [ADR-0171 — Organize Runs in one-level Research Folders](0171-organize-runs-in-one-level-research-folders.md)
- [ADR-0172 — Separate Research organization from immutable Run input](0172-separate-research-organization-from-run-input.md)
- [ADR-0173 — Delete only terminal Research without cascading Tracks](0173-delete-only-terminal-research-without-cascading-tracks.md)
- [ADR-0174 — Delete only stopped DailyTracks](0174-delete-only-stopped-dailytracks.md)

## Financial data

- [ADR-0170 — Preserve complete financial source data but author only session-aligned fields](0170-preserve-complete-financial-source-data-but-author-only-session-aligned-fields.md)
- [ADR-0175 — Store each financial statement kind as a wide version table](0175-store-each-financial-statement-kind-as-a-wide-version-table.md)
- [ADR-0176 — Ingest financial company types with explicit Field applicability](0176-ingest-all-financial-company-types-with-explicit-field-applicability.md)
- [ADR-0178 — Use consolidated statements for the six financial fields](0178-use-consolidated-statements-for-the-six-financial-fields.md)
- [ADR-0179 — Use latest annual flow fields and latest reported stock fields](0179-use-latest-annual-flow-fields-and-latest-reported-stock-fields.md)
- [ADR-0180 — Use per-instrument Tushare financial collection](0180-use-per-instrument-tushare-financial-collection.md)
- [ADR-0181 — Refresh Dataset Families independently under one Head](0181-refresh-dataset-families-independently-under-one-head.md)
- [ADR-0183 — Give each Dataset Family its own Coverage declaration](0183-give-each-dataset-family-its-own-coverage-declaration.md)
- [ADR-0184 — Start Financial Coverage in 2010 with minimal pre-start seeds](0184-start-financial-coverage-in-2010-with-minimal-pre-start-seeds.md)
- [ADR-0188 — Expose financial data only through Alpha authoring and Data readiness](0188-expose-financial-data-only-through-alpha-authoring-and-data-readiness.md)
- [ADR-0192 — Paginate the ordinary balance sheet inside one logical shard](0192-paginate-the-ordinary-balance-sheet-inside-one-logical-shard.md)
- [ADR-0219 — Drive daily financial refresh from disclosure evidence](0219-drive-daily-financial-refresh-from-cninfo-disclosures.md)
- [ADR-0232 — Resolve financial announcement triggers from stock-level Canonical deltas](0232-resolve-financial-announcement-triggers-from-stock-level-canonical-deltas.md)

## Bounded execution and operations

- [ADR-0190 — Freeze the Data Generation at ResearchRun admission](0190-freeze-data-generation-at-researchrun-admission.md)
- [ADR-0195 — Resume infrastructure retries from private ResearchRun Checkpoints](0195-resume-infrastructure-retries-from-private-researchrun-checkpoints.md)
- [ADR-0198 — Confirm execution exit before cancellation or Stop completes](0198-confirm-execution-exit-before-cancellation-or-stop-completes.md)
- [ADR-0200 — Use PyArrow and NumPy as the single columnar Research backend](0200-use-pyarrow-and-numpy-as-the-single-columnar-research-backend.md)
- [ADR-0202 — Claim ResearchRuns in strict FIFO order](0202-claim-researchruns-in-strict-fifo-order.md)
- [ADR-0206 — Retry only transient ResearchRun infrastructure failures](0206-retry-only-transient-researchrun-infrastructure-failures.md)
- [ADR-0209 — Recompute failed Tracking Advances from the authoritative Head](0209-recompute-failed-tracking-advances-from-the-authoritative-head.md)
- [ADR-0217 — Keep operational telemetry diagnostic and Product State authoritative](0217-keep-operational-telemetry-diagnostic-and-product-state-authoritative.md)
- [ADR-0218 — Scale separate Research, Batch, and Tracking pools with single-slot Workers](0218-separate-ordinary-batch-research-and-tracking-worker-pools.md)
