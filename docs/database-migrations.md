# Explicit database upgrades

Applications support one current schema. Initialization creates an empty database
or verifies the current contract; it never resets data or upgrades an existing
database automatically. A schema mismatch requires an explicit, release-scoped upgrade.
Do not change the stored fingerprint to bypass a failed check.

Each migration pins its source and target fingerprints, verifies the affected
database structure, validates source data, and records its ID, fingerprints, row
count and completion time in `thesistrace_meta.migration_history`. Unknown versions
are rejected. Repeating an already completed upgrade verifies the target constraint
and does not rewrite data. Old migration scripts remain historical release assets;
run them with their matching release checkout/image, not an arbitrary future image.

Before applying: build the target image, stop relevant writers, and take a restricted
PostgreSQL backup. Preserve referenced object-storage payloads as well. Run the
migration without `--apply` first; missing or invalid immutable results must stop
the upgrade. For the current small-data maintenance workflow, backfill and constraint
changes are atomic in one transaction. Failures roll back the database changes.
Large datasets require a separately designed bounded backfill, not an unbounded
extension of this maintenance window.

## 0001: Strategy Rank IC filters

- Source: `0a00180015bde4a1701eb9fb9e1c4b85c09d308a86ef67ca544759e1f8c2e89e`
- Target: `c11a7990cddff9a0346faca65d8f69dab299a615c02539ca8b2b45c4d28a5e48`
- Command: `python -m thesistrace.migrations.rank_ic_0001` (preflight), then add `--apply`.
- Local container entry: `node tooling/dev/runtime.mjs development run initialize python -m thesistrace.migrations.rank_ic_0001`.
  The runtime entry loads project configuration; use `pnpm dev:up` only after a successful migration.

Run this as the database owner with the target image's existing S3 configuration.
The script verifies published results through `Publication.read`, copies the
1/5/20-session Rank IC means into strategy filtering metrics, and replaces the
metric constraint. It preserves IDs, ownership, status, timestamps, prior strategy
metrics, immutable result references and all object-store contents. Undefined
Rank IC remains null; it is not fabricated or recomputed. The visible strategy
summary is unchanged.

After application, verify row counts and original result references, run normal
initialization, restart the services, and check their health and filtering behavior.
Do not restart an old application against an upgraded database. If restoration is
needed after commit, stop writers and use the verified backup and matching release.

Testing policy and isolated test entry points: [AGENTS.md](../AGENTS.md#testing).

## 0002: Bounded Publication maintenance

- Source: `c11a7990cddff9a0346faca65d8f69dab299a615c02539ca8b2b45c4d28a5e48`
- Target: `6f04fe84573259465442c092856b69714ed339c2093d51dcf67ba4b68aaa359f`
- Preflight: `python -m thesistrace.migrations.publication_maintenance_0002`.
- Apply: the same command with `--apply`, using the database owner URL.

This migration adds two durable maintenance jobs, verifies the complete new table
shape and grants access to the existing Core runtime role. Existing Publication,
Research and Dataset records are preserved. Drain and stop Core writers and the
maintenance service before applying, after taking and validating a database backup.
Start the new Core services only after the migration receipt succeeds. Initialization
verifies the new schema; it does not perform this migration automatically.

For whole-Core rollback, stop Core and maintenance, run the new image's migration
with `--reverse` (preflight), then `--reverse --apply`. The reverse transaction
archives both maintenance job states in `thesistrace_meta.maintenance_rollback_archive`,
drops only the added table, records the reverse event and restores the source
contract. Then start the matching old image. A failed forward or reverse migration
rolls back its DDL, history and fingerprint together. Reapplying after reversal
starts fresh maintenance jobs; archived progress remains available for inspection.

A maintenance-only incident can be contained by stopping
`publication-maintenance-worker`; product Workers no longer run orphan scans.
Delayed garbage collection does not prevent reading existing Results. Do not
change the fingerprint manually or restart old Core code on the new schema.

## Financial indicator ledger for 226 fields

- Source: `6f04fe84573259465442c092856b69714ed339c2093d51dcf67ba4b68aaa359f`
- Target: `624c319e2f0a11425c5a5219d8125a10234c6885ae66531df57cd384e589a693`
- Preflight: `python -m thesistrace.migrations.financial_indicator`.
- Apply: the same command with `--apply`, using the database owner URL.

This explicitly approved upgrade creates the three financial indicator ledger
tables and adds two nullable columns to financial daily refresh operations.
It verifies the affected source or target table shapes, performs DDL and records
its receipt and target contract in one transaction. Existing research, tracking,
publication and refresh rows are preserved; repeated execution verifies the target
without clearing the new ledger. Unknown source contracts or structure drift stop
the operation.

Drain and stop writers first, and verify a restricted PostgreSQL backup can be
restored before applying. A failure before commit rolls back the complete upgrade.
Recovery after commit uses that verified backup and its matching application
images after stopping writers. There is no automatic upgrade, runtime compatibility
branch, data reset or pointer fallback. Deployment and candidate publication still
require their separate acceptance and atomic Head checks.

## 0003: Seven-day Trading event retention

- Source: `1dd7bce497ec4421c87f37be66c0defc63f433d7d836e6affb1a925fa6e5b05f`
- Target: `1bb894bbece0ade8cb122d4054be492fb26ef56d1d9e85237a002f195e386a4f`
- Preflight: `python -m thesistrace.migrations.payload_retention_0003`.
- Apply: the same command with `--apply`, using the database owner URL.

Stop Core writers and Publication maintenance, verify a restricted PostgreSQL
backup, and preserve the referenced object-store bytes before applying. The
transaction checks the source Publication schema and immutable manifest inventory,
adds retention and expiry-tombstone tables, enrolls existing event payloads using
their original publication time, records a receipt and updates the schema contract.
The migration neither deletes payloads nor changes Result/Checkpoint identities.
Existing events older than seven days become due when the new maintenance worker
starts. Historical reads were not timestamped, so they cannot extend that deadline.

New explicit event reads renew the publication's diagnostic payloads for seven
days after a successful read. Report and metadata reads do not renew. Expiry releases
live references and uses the existing bounded deletion queue, preserving bytes still
referenced by other publications. API queries distinguish expired data from unrecorded
and empty data; Track pages disclose partial expiry and retain available recent rows.

Repeated application verifies the target without extending deadlines. A failed
migration rolls back tables, data and the schema receipt together. Post-commit
restoration requires the verified database and object backup with the matching
old image; do not run old code against the new schema.

## 0004: Fair Research execution opportunities

- Source: `1bb894bbece0ade8cb122d4054be492fb26ef56d1d9e85237a002f195e386a4f`
- Target: `7243074d627ca77e20ea9d5f10bed2a9ae413ca7db730d3bd37e1ff7ad5369a2`
- Preflight: `python -m thesistrace.migrations.execution_opportunities_0004`.
- Apply: the same command with `--apply`, using the database owner URL.

Drain and stop Core writers, including Research, Batch Research, Tracking, Data
Operator and Publication maintenance, and verify a restricted PostgreSQL backup
can be restored. Preserve referenced object-store bytes. The migration verifies
the existing researcher table and creates the execution opportunity table and
sequence with runtime grants. Existing records and immutable references remain
unchanged; each researcher's scheduling history starts when the new scheduler
first allocates an opportunity. No historical allocation is fabricated.

DDL, the migration receipt and the source-to-target contract transition commit
atomically. Repeating the migration verifies the table and sequence definitions
without resetting allocation state. Unknown fingerprints and affected structure
drift are rejected. Failures before commit roll back all changes. Restoration
after commit requires stopping writers and restoring the verified backup with
its matching application images. Initialize and start all Core services with the
target release after successful application.
