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

## 0005: Structured financial disclosures

- Source: `7243074d627ca77e20ea9d5f10bed2a9ae413ca7db730d3bd37e1ff7ad5369a2`
- Target: `5c82cb46665a54816e186fe74105c25ef287cc661e43fcdc8a58e4d94450ee8c`
- Preflight: `python -m thesistrace.migrations.financial_disclosures_0005`.
- Apply: the same command with `--apply`, using the database owner URL.

Drain Financial Refresh operations and stop Core writers. Build the target image,
take a restricted PostgreSQL backup and verify restoration before applying;
preserve the dataset mount and referenced object-storage bytes. A running
Financial Refresh, an unknown fingerprint or drift in an affected table blocks
the upgrade.

This adds a frozen statement collection plan, the instrument/endpoint/report-period
requirement ledger and the bounded reconciliation schedule. Existing report
facts, Dataset Head, published Generations, receipts and historical announcement
targets remain unchanged. Historical announcement rows are audit records only;
the first refresh checks `disclosure_date` and reconciles against accepted report
evidence to establish current requirements.

DDL, runtime grants, the migration receipt and the schema fingerprint commit in
one transaction. Failed application rolls back all changes; repeating a completed
upgrade verifies the affected target structures and preserves progress. For a
post-commit rollback, stop writers and restore the verified backup with its
matching application images. Start the target Core services only after the
migration succeeds. Do not reset the database or alter its fingerprint manually.

## 0006: Unified Data Refresh and Dataset Head v2

- Core source: `5c82cb46665a54816e186fe74105c25ef287cc661e43fcdc8a58e4d94450ee8c`
- Core target: `84827a4b8a6c9bb9d0171e4a7aa42cfefb061216a98295a1e7d784632c237070`
- Core preflight: `python -m thesistrace.migrations.unified_refresh_0006 --data-root <dataset-mount> --benchmark-root <benchmark-mount> --backup-directory <restricted-backup>`.
- Auth source: `479089ee38d20700e10a0f955ee153eb2644e6925d4cb671009a728a161b1d5e`
- Auth target: `d64b69665b7454cd602a81295df4deb99b5f336a6df58a6cb66dc3b35aa3a4eb`
- Auth preflight: `node apps/auth/dist/migrate-unified-refresh.js --backup-directory <restricted-backup>` with the target build and owner database URL.
- Apply: run each preflight command with `--apply` after saving a verified PostgreSQL backup as `<restricted-backup>/database.dump`.

Drain all queued/running refreshes and stop Core, Data Operator and Auth writers.
Back up the database, Dataset mount, Benchmark mount and referenced objects before
application. Keep the three directory arguments independent. Neither initializer
performs an upgrade or accepts the previous contract at runtime.

Core adds durable preparation checkpoints and retry lineage, retains historical
family receipts, and permits financial candidates to be prepared without publication.
The database DDL, fingerprint and migration history commit in one transaction;
a failed step rolls them all back. The explicit Head conversion then imports the
existing Benchmark bytes into an immutable Snapshot, backs up Head v1, and replaces
Head atomically with v2 containing the Snapshot reference. The Generation and data
identity are preserved. If interrupted after the database commit, repeat the same
command to finish the Head conversion before starting services. Repeated application
verifies the current schema, Head and selected Snapshot without rewriting history.
Auth adds the unified submission Proof operation while preserving old audit records;
its constraint, fingerprint and receipt commit together and roll back together.

Only start the target release after both receipts succeed. A post-commit rollback
requires stopping writers and restoring the verified database and both mounts with
the matching old release. Do not run the old application against the upgraded state
or change fingerprints manually. Verification follows [AGENTS.md](../AGENTS.md#testing).

## Explicit research-contract retirement

`python -m thesistrace.migrations.research_contract_cutover` is an operator-only
retirement command, never an application startup action. Use the approved target
checkout/image and its Core environment settings, with the database owner (including
permission to read `pg_control_system()`) and the matching Publication S3 store.
Drain and stop Research, Batch, Tracking and Publication maintenance writers first.
Do not execute this on the daily development environment until final feature
qualification authorizes that environment's cutover.

This operation does not change relational schema or its fingerprint. Its source
and target schema must both equal this checkout's current schema. A different
schema needs its separate explicit migration first. Supply a JSON file containing
exact `factor`, `strategy`, and `kernel` source versions; current and incomplete
contracts are rejected. Other historical contracts require their own reviewed
preview and are not implicitly included.

```sh
python -m thesistrace.migrations.research_contract_cutover preview \
  --source-contract source-contract.json --output preview.json
python -m thesistrace.migrations.research_contract_cutover apply \
  --plan preview.json --backup backup.json
python -m thesistrace.migrations.research_contract_cutover status --id CUTOVER_ID
python -m thesistrace.migrations.research_contract_cutover resume --id CUTOVER_ID
```

The preview's printed `id` identifies the exact canonical preview. Review its
cluster/database and S3 endpoint/bucket identities, contracts, selected IDs/counts, descendant inventory,
and retained/exclusive Publication references. A mixed Batch or retained Track
that depends on selected research blocks retirement. A stale preview, active
execution/pin, missing Publication metadata or inconsistent ownership fails
before authority changes. Dataset files, Dataset state, identities, unrelated
research and current-contract records are outside retirement scope. Run ownership
tombstones and Dataset pin history are preserved.

`apply` takes schema/Publication locks and write-blocking locks on affected tables,
rechecks the full inventory, then writes a private, fsynced JSON backup before its
single metadata transaction deletes selected records. The backup records the
preview and affected metadata, including copied Publication links; it does not
copy object-store bytes. A new preview file never overwrites evidence. Retrying
an uncommitted operation can reuse its backup only when its bytes exactly match
the newly verified inventory. A partial or different backup is rejected; preserve
it for diagnosis and choose a new backup path after reviewing a fresh preview.

`status` reports `not_committed` when no authority receipt exists. Failed metadata
transactions roll back references, records and the receipt together; their durable
backup remains. Successful `apply` records `committed` and the exact object list
in `thesistrace_meta.research_cutovers`. Repeating `apply` verifies its backup and
returns the existing receipt. Apply, status and resume reject changed database or
object-store coordinates before modifying records or bytes. Credentials are not
stored in the preview. Save the command's exit status and stderr alongside
the private preview/backup for failed-attempt diagnostics.

`resume` processes only that receipt's pending object hashes, rechecks references
through the shared Publication collector, and commits each object's outcome and
progress independently. Status becomes `collecting`, then `complete`. It preserves
objects acquired by retained manifests and never drains unrelated queue entries.
Failure after a byte deletion but before the progress commit leaves that hash
pending; repeated deletion is idempotent. Ordinary maintenance may also complete
a queued hash, which resume records as already collected. Keep the backup at its
recorded absolute path: repeated apply, status and resume verify its SHA before
proceeding. This is destructive retirement, not a reversible schema downgrade;
once exclusive bytes are reclaimed, its metadata-only backup cannot restore those
bytes. Stop writers and preserve a separate full database/object-store backup if
post-commit restoration is required.

## 0007: Independent Strategy Batches

- Source: `84827a4b8a6c9bb9d0171e4a7aa42cfefb061216a98295a1e7d784632c237070`
- Target: `423422281705fa7018c712268141c15fc58de13de7d1b46523a449e84a66c00d`
- Preflight: `python -m thesistrace.migrations.independent_strategies_0007`.
- Apply: add `--apply --database-backup /restricted/path/database.dump` as database owner.

Drain active Batches, stop Core writers and verify a restorable PostgreSQL backup.
The migration preserves existing Batches, ResearchRuns, Results and timestamps. It
extends Batch and cancellation constraints, permits separate active independent
Strategy task attempts, and adds nullable per-task live progress. Live progress is
not a recovery checkpoint. The affected tables and indexes are verified against
the pinned release before and after changing them. DDL, migration receipt and
schema fingerprint commit atomically; failure rolls everything back. Repeating
the command verifies the target without rewriting rows. Unknown versions, structural
drift and active Batches reject the upgrade. Post-commit rollback requires the
verified backup and matching old application; initialization never migrates itself.

## 0009: Measured ResearchRun execution time

- Source: `423422281705fa7018c712268141c15fc58de13de7d1b46523a449e84a66c00d`
- Target: `d6ee5f41c2c3c9fa8a49d5adf530eb4e98c9f9c8cb3fd5fff1408a1a157115a9`
- Preflight: `uv run --project apps/core python -m thesistrace.migrations.execution_timing_0009`.
- Apply: add `--apply --database-backup /restricted/path/database.dump` as database owner.
- Optional historical evidence: `--measurements /restricted/path/execution-measurements.json`.

Drain active research and stop Core writers before upgrading. Save and verify a
restorable PostgreSQL backup. This migration adds nullable processing counters to
ordinary Attempts and Batch task Attempts, preserving all existing research,
Results, lifecycle timestamps, and ownership. Historical counters remain unknown
unless exact measurements are supplied; lifecycle duration is never substituted.

The optional file has schema version `research-execution-measurements-v1`, the
source schema fingerprint, and a `measurements` array. Each entry contains
`owner` (`ordinary_attempt` or `batch_task`), `attempt_id`, finite nonnegative
`processing_seconds`, and `chunk_ordinal` (zero for a Batch task). Only known
terminal Attempts are accepted. Duplicate entries, conflicting measurements,
active writers, unsupported versions, and structural drift reject the upgrade.

Table changes, evidence backfill, migration receipt, and schema fingerprint are
transactional. Failure rolls everything back; repeat execution verifies the
contract and existing values. After commit, restoration requires the verified
backup and matching release. Initialization does not perform migrations.

## Auth 0002: Email-only identity

- Source: `d64b69665b7454cd602a81295df4deb99b5f336a6df58a6cb66dc3b35aa3a4eb`.
- Target: `1726410065771dea71f1f81b83deee4de87f219c08b86c649d8d0c479b7eec7e`.
- Preflight: `node apps/auth/dist/migrate-retire-invitations.js --backup-directory /restricted/path/backup`.
- Apply: add `--apply` after saving a restorable PostgreSQL backup as `database.dump` in that directory. Set `THESISTRACE_OWNER_DATABASE_URL` to the intended database owner connection.

Stop Auth writers before applying and keep the backup private. The command rejects
unknown releases and verifies the complete source and target catalogs. Existing
identities, account rows, Sessions, Operator assignment and research ownership are
preserved. Invitation and password-reset tables move to the owner-only
`thesistrace_auth_migrations` schema; their foreign keys are detached so later
identity cleanup cannot erase archived history. Retired Operator proofs, security
audit events and reset verification records are copied there before removal from
live tables. Current sign-in and Operator email-verification codes remain intact.
Auth and Core runtime roles have no archive access.

Before starting the new release, remove `THESISTRACE_DEV_RESEARCHER_PASSWORD`
from an existing private configuration file. New configurations no longer define
it; Development identities use the same email-verification login as other users.

Archive moves, row changes, constraints, the database migration receipt and schema
fingerprint commit in one transaction. Failure rolls them back together. Repeating
an applied migration verifies the target without rewriting records. The command
also writes a private `auth-0002-receipt.json` recording the backup SHA-256 and the
source and target fingerprints. Post-commit restoration requires the verified
backup and the matching previous application. Initialization never applies this
upgrade automatically. Older Auth releases first use the explicit Auth 0001
upgrade to reach the declared source; that migration retains its frozen target
catalog and does not dispatch across runtime versions.

## 0010: Indexed Research Run search

This search upgrade follows the fixed 0009 execution-timing contract.

- Source: `d6ee5f41c2c3c9fa8a49d5adf530eb4e98c9f9c8cb3fd5fff1408a1a157115a9`
- Target: `a40cd7fedf6025c2c2f1ac096a26cbe60ab4c85a868d49f0cf9f087f697408e0`
- Preflight: `python -m thesistrace.migrations.research_search_0010`.
- Apply: add `--apply --database-backup /restricted/path/database.dump` as database owner.

Stop Core writers, take a restricted PostgreSQL backup and verify restoration before
applying. The migration adds `pg_trgm` in the `research_runs` schema, two stored
generated columns for normalized notes and formula text, and one multicolumn GIN
index covering name, notes and formula. PostgreSQL maintains these values and the
index atomically on writes. Existing names, immutable inputs, IDs, ownership,
Results and timestamps are preserved; object storage is unchanged.

Backfill, index creation, structural verification, the migration receipt and the
schema contract commit together. Both columns are added in one table rewrite.
The operation takes an exclusive table lock, with a five-second lock timeout and
a 120-second statement timeout. Schedule a maintenance window; this is not an
online upgrade for arbitrarily large histories. Unknown versions and structure
drift fail closed. A failure rolls back columns, extension, index and receipt;
repeated application verifies the target without rewriting history. Post-commit
restoration uses the verified backup and matching application release.

Initialize and restart all Core services with the target image after the migration.
Search remains a case-insensitive literal substring match scoped to the researcher.
Trigram indexes accelerate selective terms; short terms such as two-character
Chinese words can instead use the existing researcher index and scan that user's
compact search columns. Matching IDs and sort values are materialized once for
the exact total and page, and only the page retrieves complete immutable inputs.

## Billing: Auth 0003, Core 0011 and Agent 0001

Stop Auth, Core and Agent writers and preserve a verified private PostgreSQL backup
before applying all three upgrades. Startup only verifies the current contract; it
never upgrades existing schemas automatically. All release source/target assets are
frozen, including the previous search migration's target.

| Owner | Source fingerprint | Target fingerprint | Preflight / apply entry |
| --- | --- | --- | --- |
| Auth | `1726410065771dea71f1f81b83deee4de87f219c08b86c649d8d0c479b7eec7e` | `1b50ec71fe68647a99ccdcf76c76fc1d5fa05cd59673bda0028f6fd7c22ce386` | `node apps/auth/dist/billing-migrate.js --backup-directory <private-backup>` |
| Core | `a40cd7fedf6025c2c2f1ac096a26cbe60ab4c85a868d49f0cf9f087f697408e0` | `702d259e8393f789b1ac8a04e6192d443ccd56a46647e02a238b1ea0220e762e` | `python -m thesistrace.migrations.billing_0011` |
| Agent | `0f28e823f7a7128e7e4eba004584ca58475d9df737006a1899965f97b358099e` | `639450f161abbaba6c0314465024effbb9b9ddf3eb1d0cf24a91569145149577` | `node apps/agent/dist/model-settlement-migrate.js --backup-directory <private-backup>` |

Use `THESISTRACE_OWNER_DATABASE_URL` for the Node commands and an owner
`THESISTRACE_DATABASE_URL` for Core. Apply with `--apply`; Node requires the verified
backup at `<private-backup>/database.dump`, while Core also requires
`--database-backup <verified-dump>`. Node receipts include the backup SHA-256; all
three transactions record their version transition and preserved row counts.

Auth adds payment associations, paid entitlements, adjustments, the verified event
inbox and command receipts without changing identities. Core adds durable quota
settlement to retained Run ownership and persistent tracking selection. Deleted
historical Run ownership remains consumed; failed and unstarted canceled retained
Runs release their original-day quota. Agent preserves existing settled charges,
retains unknown reservations and adds explicit settlement state and Run association.
No existing paid customers are manufactured or migrated.

Preflight, target structure, repeated execution, owner access and late-receipt
rollback are verified in isolated database tests. After applying all upgrades,
run ordinary initialization/verification, compare preserved identities, ownership,
tracks and costs, then restart the matching new services. Restore a committed
upgrade only by stopping writers and restoring the verified backup with its matching
release; never reset data or rewrite a fingerprint to bypass verification.

Product and merchant configuration: [Creem billing](creem-billing.md).
