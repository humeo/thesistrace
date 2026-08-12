# ThesisTrace Core Architecture

> Status: current module-first Core architecture.

## Product boundary

ThesisTrace currently closes one local, single-operator research loop:

```text
Data Operator prepares the current Dataset Head
    -> Data Overview exposes current coverage read-only
    -> save and run a Research Definition for selected dates
    -> a ResearchRun Attempt pins the current Data Generation
    -> immutable Factor and Strategy Result
    -> optionally start a DailyTrack
    -> later market sessions advance that Track
```

The user-visible resources are Data Overview, Research Definitions,
ResearchRuns, and DailyTracks. Data Generation, execution Attempt, Tracking
Checkpoint, Working Cache, publication manifest, and schema fingerprint are
implementation concepts, not additional product resources.

Login, tenancy, collaboration, hosted deployment, and production operations are
not part of the active system. There is no Local/Hosted product mode.

## Runtime topology

One Compose topology contains Web, API, Worker, PostgreSQL, RustFS, and a
one-shot schema initializer. Persistent Development and disposable Test use the
same product implementation with different Compose identities, ports, volumes,
and data mounts.

```mermaid
flowchart LR
    B["Browser"] --> W["Web"]
    W --> H["HTTP adapter"]
    H --> M["Core modules"]
    K["Worker"] --> M
    O["Private Data Operator"] --> D["Data module"]
    M --> P["PostgreSQL"]
    M --> S["RustFS via S3 client"]
    D --> F["Mounted Canonical Data Store"]
```

PostgreSQL stores product lifecycle state, action receipts, attempts, data
operation state, pins, and publication manifests. RustFS stores immutable
ResearchRun and DailyTrack publication bytes. The mounted Canonical Data Store
contains the current Dataset Head and immutable-while-referenced Data Generation
files. No runtime downloads data during API or Worker startup.

## Modules and dependency direction

```text
src/thesistrace/
├── data/
├── definition/
├── research_run/
├── daily_track/
├── research_kernel/
├── publication/
├── entrypoints/
└── _postgres/
```

Each product module owns its rules, PostgreSQL schema, SQL, lifecycle state, and
product projection. HTTP and Worker entrypoints are adapters; they do not own
product sequencing. The Research Kernel is pure and knows no product IDs,
PostgreSQL, S3, HTTP, Worker, or Data Operator concepts.

```mermaid
flowchart LR
    E["HTTP and Worker entrypoints"] --> D["Definitions"]
    E --> R["ResearchRuns"]
    E --> T["DailyTracks"]
    E --> A["Data"]
    D --> A
    D --> K["Research Kernel"]
    D --> R
    R --> A
    R --> K
    R --> P["Publication"]
    R --> T
    T --> A
    T --> K
    T --> P
```

Cross-module writes happen only through explicit private interfaces inside one
concrete PostgreSQL transaction. Product modules do not reach into another
module's tables to implement product rules.

The private `_postgres` package owns the connection pool, concrete transaction
helper, and current-schema initializer/verifier. It contains no domain SQL and
offers no migration history or compatibility machinery.

## Schema lifecycle

The active checkout defines exactly five product schemas:

```text
publication
data
definitions
research_runs
daily_tracks
```

Their complete current definitions live in each module's `schema.sql`.
Initialization is allowed only when none of the product schemas or
`thesistrace_meta` exists. The initializer creates the schemas and records one
fingerprint of the complete contract in `thesistrace_meta.schema_contract`.

API, Worker, and Data Operator startup verify the exact schema set and
fingerprint. Partial state or a mismatch fails immediately. Development fixes a
mismatch with the destructive `pnpm dev:reset`; Test always starts from an empty
isolated database. There is no upgrade, downgrade, fallback, or compatibility
path.

## Data

The product interface is read-only:

```text
GET /api/data -> coverage, data-through session, last refresh, readiness
```

Bootstrap, Refresh, inspection, work execution, and garbage collection belong
to the deployment-private `thesistrace-data-operator` command. They are not HTTP
routes or Web actions.

Bootstrap creates the first complete Data Generation and Dataset Head. Refresh
collects a bounded overlap plus new completed sessions, builds and validates a
candidate beside the active Generation, and atomically moves the Head only if
the expected Head is still current. Failure leaves the previous Head readable.

An active execution pins one Data Generation. Garbage collection retains the
current Head, live candidates, and active pins; completed Results and Tracking
state do not promise permanent retention of their input market-data bytes.

Tushare is the live source adapter. Replay is the deterministic operator and
test adapter. Neither source adapter owns product IDs, lifecycle state, or the
Dataset Head transition.

## Research Definitions

Definitions are mutable authoring resources with optimistic revisions. Save may
retain incomplete content. Run saves the submitted revision and requires a
complete runnable definition, including selected start and end dates.

```text
list / get / create / save
authoring_options
run(current content, expected revision, request ID)
```

Run validates the requested Research Period against the current Dataset Head,
freezes the research question, calculation contracts, and selected Data
Generation, then atomically admits a queued ResearchRun with durable Generation
retention. Claim replaces that retention with an Attempt pin before data opens.

The same request ID and fingerprint returns the original outcome. Reusing the
ID with different input is a conflict. Invalid runnable semantics preserve the
saved Definition but create no ResearchRun.

## ResearchRuns

ResearchRun creation is available only through the Run action. Reusing an
earlier Research requires Use as Draft followed by an ordinary Run action.

```text
queued -> running -> succeeded | failed
queued | running -> cancelled
```

When an Attempt starts, it atomically pins the Data Generation frozen at Run
admission. The pin remains fixed for the complete calculation even if Refresh
moves the Dataset Head concurrently. A retry pins the same frozen Generation
and recomputes from the beginning; retryable gaps retain that Generation and
partial outputs are never combined.

Use as Draft copies an earlier Run's authorable values into browser-local state.
Submitting that Draft follows ordinary compilation and admission, including a
fresh current Data Generation selection, and creates a new ResearchRun. Edits
never mutate the original Run.

A succeeded Run exposes one immutable Result containing bounded Factor
summaries, Strategy metrics and daily observations, benchmark results, terminal
Strategy state, and provenance. Publication failure cannot expose a partial
Result or mark the Run succeeded. Cancel commits durable terminal state first;
fencing rejects late Worker publication.

## DailyTracks

A succeeded ResearchRun can activate at most one DailyTrack. Activation freezes
the complete Tracking Origin and initial Strategy state. The current product
permits at most ten active or blocked Tracks; stopped Tracks do not count.

```text
active | blocked | stopped
```

An active Track compares its latest successful session coordinate with the
current Dataset Head and advances later Research Sessions in order. Each
Tracking Advance Attempt pins one current Data Generation. Only a complete
immutable Checkpoint moves the Tracking Head. A concurrent Data Refresh is
handled by later work rather than by mixing Generations inside one Attempt.

After bounded retries are exhausted, a Track becomes blocked and retains its
last successful Head. Retry continues from that Head. Stop is irreversible.

The Working Cache is a private, bounded, disposable optimization. PostgreSQL
state and immutable Checkpoints remain authoritative. Missing or invalid cache
state is rebuilt; startup reconciliation removes cache state for stopped Tracks.

## Research Kernel and Publication

The Research Kernel owns Alpha evaluation, label maturation, Factor aggregation,
Strategy transitions, numeric semantics, and deterministic ordering. Its Run
and Advance paths share one implementation of those rules. Operators form a
closed versioned catalog; there is no runtime plugin or arbitrary Python/SQL
execution.

Publication is the shared module for immutable ResearchRun Results and
DailyTrack Checkpoints. It hides canonical serialization, checksums,
content-addressed S3 keys, manifest recording, verified reads, and orphan-safe
failure behavior.

Publication order is fixed:

1. Canonically serialize and hash every payload.
2. Upload immutable bytes to their content-addressed keys.
3. In one PostgreSQL transaction, record the manifest and move the owning
   module's fenced lifecycle reference.
4. Treat the publication as visible only after commit.

An uploaded object followed by a PostgreSQL failure is invisible and may be
collected later. Readers start from the PostgreSQL reference and verify every
referenced object.

## Product routes

```text
/data
/definitions
/definitions/:definitionId
/research-runs
/research-runs/:runId
/daily-tracks
/daily-tracks/:trackId
```

The Web modules own page-local loading, errors, refresh, and actions. The HTTP
adapter maps typed requests to module interfaces. It does not expose Data
Operator controls, physical paths, S3 keys, manifests, SQL fields, Attempt
administration, authentication, or deployment modes.

## Worker

Durable PostgreSQL state is work acceptance. The Worker polls module-owned work
every five seconds. ResearchRuns and DailyTracks claim and fence their own
Attempts; there is no Temporal, outbox relay, event bus, global job table, or
generic dispatch interface.

## Verification

The active local gates are documented in the
[local lifecycle guide](../runbook/local-lifecycle.md):

1. `mise exec -- pnpm test` runs fast host checks.
2. `mise exec -- pnpm test:integration` exercises real PostgreSQL and RustFS in
   a fresh isolated Compose Test project.
3. `mise exec -- pnpm test:e2e` drives the complete browser loop against a fresh
   topology.
4. `mise exec -- pnpm test:image-smoke` qualifies the built application images.
5. `mise exec -- pnpm check` is the ordinary merge gate;
   `mise exec -- pnpm check:release` adds image qualification.

Live Tushare credential verification is a separate explicit gate. Local checks
are not Production readiness.

## Deliberately absent

- Schema migration, compatibility, fallback, or downgrade paths.
- User-facing Dataset Release history or Data Refresh controls.
- Login, users, tenants, workspaces, quotas, collaboration, or billing.
- Hosted deployment, Temporal, event relay, generic scheduler, or event bus.
- SQLite Product State or a second runtime implementation.
- Raw artifact browsers, physical object paths, or internal lifecycle pages.

The current domain vocabulary is defined in [`CONTEXT.md`](../../CONTEXT.md).
Operator commands are documented in the
[Data Operator runbook](../runbook/data-operator.md).
