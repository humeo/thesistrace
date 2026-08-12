# Alpha Language and Research Workspace

**Status:** ready-for-agent

## Outcome

Replace the visible Definition/Revision workflow and the fixed Alpha builder with one
formula-first Research workspace:

```text
Browser Draft
    -> backend diagnostics
    -> Run admission and authoritative compile
    -> immutable ResearchRun input
    -> transient Series Execution Plan
    -> Research result / optional DailyTrack
```

The user edits one DSL expression and clicks **Run**. The server persists only accepted
research events and their results. Research Folders organize those events; they do not
store authoring content or execution state.

This specification freezes the decisions recorded in `CONTEXT.md` and ADRs 0157-0169,
0171-0174, and 0182. It is ready to be decomposed into implementation issues, but those
issue files have not yet been created.

## Product invariants

### Alpha authoring

- An Alpha Formula is exactly one expression and end of input.
- Fields and builtins use stable lowercase `snake_case` Alpha Identifiers in one global
  namespace. Field references have no `$` prefix.
- V1 permits numeric literals, field references, parentheses, unary `-`, binary `+`,
  `-`, `*`, `/`, and named builtin calls.
- Statements, assignment, variables, control flow, imports, attributes, indexing,
  collections, comprehensions, keyword arguments, and user-defined functions are not
  part of the language.
- The static value model is `Numeric Series`, `Number`, and `Window`. The root value
  must be `Numeric Series`.
- Platform maintainers add fields and builtins in code. Users cannot upload or execute
  Python, UDFs, plugins, or arbitrary code.
- There is one current append-only Alpha Language. There is no user-visible or persisted
  Alpha Release ID, operator release, or multi-version dispatcher.

### Research workspace

- The frontend calls a `ResearchRun` a **Research**. There is no durable Research or
  Definition object between Folder and ResearchRun.
- Every ResearchRun belongs to exactly one one-level Research Folder.
- One system-owned Default Folder is created deterministically and cannot be deleted.
  Global **New Research** targets it; users can also create named custom Folders.
- Folder names are user-editable. Folders do not nest and cannot be deleted while they
  contain Runs.
- Research name and `folder_id` are mutable organization metadata outside immutable Run
  input. Names may repeat. `run_id` is identity.
- A blank Research name is stored as `Research <short-run-id>` after admission.
- Lists distinguish duplicate names with creation time, status, and a formula summary.

### Browser Draft

- A Draft exists only in the browser and has no server identity.
- There is exactly one Draft per Folder. The smallest implementation uses
  `localStorage`; IndexedDB is not needed for the current bounded text payload.
- A missing Draft opens empty. The UI never restores the latest Run implicitly.
- Run does not clear or rewrite the Draft.
- **New** clears the current Folder Draft. **Use as Draft** copies one historical Run's
  frozen authoring input into the target Folder Draft.
- New and Use as Draft require confirmation only when they would overwrite unexecuted
  local changes.
- Cross-device Draft synchronization is out of scope. If required later, it receives a
  separate server Draft Resource instead of changing Folder or ResearchRun semantics.

### Lifecycle and deletion

- Run admission compiles the submitted Formula authoritatively before durable mutation.
  Rejected input produces diagnostics and no Folder child, Run, receipt, or queue item.
- Accepted admission atomically creates one queued ResearchRun containing the complete
  immutable input snapshot and its compiled Alpha Expression.
- A Worker executes the stored compiled Expression. It never recompiles Formula source
  and never reads mutable browser or Folder state.
- Infrastructure retry remains a ResearchRun Attempt. The product-level **Rerun** action
  and `rerun_of_id` do not exist.
- Reuse is only **Use as Draft -> Run**, which creates a new independent ResearchRun.
- Only `succeeded`, `failed`, or `cancelled` Research can be permanently deleted.
  `queued` or `running` Research must first reach a terminal state.
- Research deletion never cascades to DailyTrack. A surviving Track keeps its complete
  origin snapshot and displays a deleted seed ID as text rather than a broken link.
- Only a stopped DailyTrack can be permanently deleted. Active or blocked Tracks must be
  stopped explicitly first.

### Development constraint

- Do not add a compatibility endpoint, fallback parser, dual-write, schema migration,
  backfill, feature flag, or old/new runtime switch.
- Intermediate modules may be built and tested before routing is switched, but the final
  runtime has only the new path. Development databases are reset to the new schema.

## Current implementation gaps

| Area | Current fact | Required change |
| --- | --- | --- |
| Data field catalog | `src/thesistrace/data/fields.py` has six `AuthorableField` records and an `evaluation_name` binding. | Replace this authoring-only list with Data-owned canonical `FieldDefinition` records carrying optional typed `AlphaFieldCapability`. |
| Physical field mapping | `src/thesistrace/data/canonical_mapping.py` consumes `AUTHORABLE_FIELDS`; `src/thesistrace/research_kernel/alpha.py` also carries hard-coded canonical keys. | Data owns Alpha Identifier resolution and Series reading. Remove Kernel and frontend physical-key maps. |
| Alpha syntax | `src/thesistrace/research_kernel/alpha_expression.py` validates a normalized JSON node tree and manufactures Python AST. | Accept Formula text, parse a strict Python-expression subset, resolve and type-check it, then emit ThesisTrace's own immutable Expression. |
| Builtins | Operator metadata is in `alpha_expression.py`, while execution branches are in `research_kernel/alpha.py`. | One code-owned `BuiltinDefinition` owns signature, documentation, lookback, missingness, numeric behavior, evaluator, and work estimate. |
| Execution | `research_kernel/alpha.py` validates again and evaluates via operator branches. | Build a postorder Series Execution Plan from the stored Expression and compute every node once. Share it between batch ResearchRun and incremental DailyTrack paths. |
| Admission | `definition/service.py` saves/increments a Definition revision before Run validation. | Compile first; on success insert one ResearchRun atomically. Remove Definition save/revision behavior. |
| Run snapshot | `research_run/models.py::ImmutableRunInput` embeds Definition, revision, field bindings, and semantic versions. | Store Formula source, compiled Expression, field bindings, research parameters, calculation contracts, and data snapshot facts directly. Do not store Definition, Revision, Alpha/operator Release IDs, name, or Folder in the snapshot. |
| Persistence | `definition/schema.sql` stores Definitions and Run receipts; `research_run/schema.sql` stores Definition and rerun references. | Add one-level Folders and mutable Run organization columns; remove Definition tables, revisions, rerun fields, and rerun receipts from the fresh schema. |
| HTTP interface | `entrypoints/http.py` exposes Definition CRUD/run and ResearchRun rerun. | Expose Alpha catalog/diagnostics, Folder operations, direct Run admission, mutable Run organization, terminal deletion, and stopped Track deletion. Remove obsolete endpoints. |
| Runtime composition | `entrypoints/runtime.py` constructs `DefinitionService`; `entrypoints/schema.py` installs the Definition schema. | Compose the Alpha Language, Research Folder, and ResearchRun admission modules; remove Definition runtime/schema registration. |
| Frontend | `web/src/definitions/DefinitionsPage.tsx` exposes Save, Run, Refresh, Revision and a root-only builder; `ResearchRunsPage.tsx` exposes Rerun. | Replace Definitions with a Research workspace and DSL editor; add Folder navigation and local Draft persistence; replace Rerun with Use as Draft. |
| Tests | Acceptance and shell tests are centered on Definition save/revision and rerun. | Replace tests at the new module interfaces; do not retain obsolete tests as a second behavioral contract. |

## Target module design

### 1. Data-owned Alpha Fields

Data exposes one deep module with two caller-facing operations:

```python
alpha_field_catalog() -> tuple[AlphaFieldDefinition, ...]
read_alpha_series(field_ids, observation_scope) -> FieldFrame
```

`AlphaFieldDefinition` is a projection derived from a canonical `FieldDefinition`, not a
second registry. The canonical definition owns point-in-time meaning, grain, physical
type, unit, availability, and missingness. Its optional capability is equivalent to:

```python
AlphaFieldCapability(
    identifier="close_adj",
    value_type="numeric_series",
)
```

The compiler resolves `close_adj` to the stable canonical field ID
`price.close.adjusted`. The compiled Field Reference stores that canonical ID. The
evaluator requests Series by canonical ID, so callers never learn a row key or
`evaluation_name` mapping.

The production Data reader and deterministic test reader are adapters at this seam.

### 2. Alpha Language

The Alpha Language is a deep in-process module. Its external interface is limited to:

```python
catalog() -> AlphaAuthoringCatalog
diagnose(source: str) -> FormulaDiagnostics
compile(source: str) -> CompiledAlpha
```

`CompiledAlpha` contains the immutable ThesisTrace Expression, resolved field bindings,
static result type, effective lookback, node/depth counts, and estimated work. Python's
`ast.parse(source, mode="eval")` is an internal parser only. The implementation walks an
exhaustive allowlist and converts accepted nodes immediately. Nothing calls Python
`compile`, `eval`, or `exec`, and Python AST never crosses the module interface or enters
the database.

Diagnostics have a stable structure:

```json
{
  "code": "UNKNOWN_IDENTIFIER",
  "message": "Unknown Alpha identifier: closes",
  "severity": "error",
  "range": {
    "start": {"offset": 8, "line": 1, "column": 9},
    "end": {"offset": 14, "line": 1, "column": 15}
  }
}
```

Unknown fields and unknown builtins share `UNKNOWN_IDENTIFIER`; a call to a field or a
bare builtin additionally receives `NOT_CALLABLE` or `EXPECTED_FIELD` where applicable.
Syntax, arity, type, window, non-finite literal, source length, node count, depth,
lookback, and work-budget failures each have stable codes and source ranges.

The Alpha Authoring Catalog composes Data field projections with public builtin
projections and fails application readiness on duplicate or invalid identifiers. It
contains only identifiers, types, parameter help, descriptions, examples, and bounds;
evaluator callables remain private.

### 3. Builtin Catalog and Series execution

Each builtin has one immutable code-owned `BuiltinDefinition` containing:

- stable Alpha Identifier;
- typed positional parameters and result rule;
- description and examples;
- effective-lookback function;
- missing-value and numeric policy;
- vectorized evaluator;
- deterministic work estimator.

The Series evaluator exposes one operation:

```python
evaluate(expression, field_frame, execution_scope) -> NumericSeries
```

Its implementation converts the Expression into a transient postorder plan, evaluates
each node once, and owns scalar broadcasting, alignment, finite-number handling,
missingness, and division behavior. ResearchRun batch execution and DailyTrack
incremental execution call this same interface; they do not implement builtin branches.

Admission constants for maximum source length, node count, depth, effective lookback,
and estimated work live with the compiler. The effective-lookback ceiling remains 252
Research Sessions. The remaining ceilings must be fixed from a committed benchmark on
the repository's representative maximum universe/date range before the Run endpoint is
enabled; shipping with unset, environment-dependent, or request-controlled limits is
not acceptable.

### 4. ResearchRun admission and lifecycle

The admission module has one command interface:

```python
admit_research(command: AdmitResearch) -> ResearchRun
```

It performs, in order:

1. request-schema validation;
2. authoritative Formula compile and budget validation;
3. Dataset Head/date/field availability admission;
4. immutable input construction and checksum;
5. one transaction inserting the queued Run and its idempotency key;
6. post-commit queue notification through the existing durable claim path.

The Run row itself owns a unique `request_id`; a repeated identical request returns the
same Run, while reuse of the key with a different payload returns `409`. Rejected
commands persist nothing. No separate successful-admission receipt is needed.

The immutable input contains:

- Formula source and compiled Alpha Expression;
- Hypothesis and requested Research dates;
- resolved identifier-to-canonical-field bindings;
- Universe, neutralization, strategy, costs, risk-free rate, and numeric contracts;
- selected Dataset Head/generation facts required by existing provenance rules.

Mutable `name` and `folder_id`, lifecycle status, timestamps, Attempts, failure summary,
and result pointers remain outside that value. Existing claim, retry, cancellation,
publication, and provenance invariants continue unless this specification explicitly
replaces them.

### 5. Browser Research workspace

Use CodeMirror 6 as the editor adapter after confirming its current package/types during
implementation. It provides source ranges, completion, hover/help, and diagnostics
without moving language authority into the browser. Do not reproduce the grammar in a
second frontend parser.

The web module:

- loads `/api/alpha/catalog` for completion and help;
- debounces `/api/alpha/diagnostics` while editing;
- always submits the complete current Draft to Run, which compiles again;
- stores one small JSON Draft at `thesistrace.research-draft:<folder_id>`;
- starts empty when that key is absent or explicitly cleared;
- records a local baseline after a successful Run so overwrite confirmation can
  distinguish executed from unexecuted edits, without clearing the Draft. The baseline
  is the exact submitted snapshot accepted by that Run; edits made while it is pending
  remain unexecuted;
- implements Use as Draft entirely in the browser from the selected Run detail;
- uses the server only for Folders, accepted Runs, and lifecycle actions.

The Formula remains usable when the diagnostics request is temporarily unavailable. Run
does not fall back to browser validation; the server either admits or rejects it.

## HTTP interface

### Alpha authoring

- `GET /api/alpha/catalog` -> field and builtin authoring projections.
- `POST /api/alpha/diagnostics` -> `200` with `{valid, diagnostics}` and no mutation.
  Request-shape failures still return `422`.

### Research Folders

- `GET /api/research-folders`
- `POST /api/research-folders` with a nonblank name
- `PATCH /api/research-folders/{folder_id}` to rename a custom Folder
- `DELETE /api/research-folders/{folder_id}` only for an empty custom Folder

Deleting the Default Folder returns `409`; deleting a nonempty Folder returns `409` and
does not move or delete Runs.

### Research

- `POST /api/research-runs` admits the submitted Draft directly. Success returns `202`
  with the queued ResearchRun; Formula/admission failure returns `422` with structured
  diagnostics/issues and performs no durable mutation.
- `GET /api/research-runs?folder_id=...&cursor=...`
- `GET /api/research-runs/{run_id}` includes frozen authoring input required by Use as
  Draft and existing result detail.
- `PATCH /api/research-runs/{run_id}` changes only `name` and/or `folder_id`.
- `POST /api/research-runs/{run_id}/cancel` retains current idempotent cancellation.
- `DELETE /api/research-runs/{run_id}` deletes terminal Research only.
- `POST /api/research-runs/{run_id}/daily-tracks` retains explicit Track creation.

There is no Definition CRUD/run endpoint and no ResearchRun rerun endpoint.

### DailyTrack

- Existing list, detail, retry, and stop operations remain.
- `DELETE /api/daily-tracks/{track_id}` deletes only a stopped Track and its Track-owned
  state. Active or blocked states return `409`.

## Persistence cutover

The fresh PostgreSQL schema contains:

- `research_run.folders`: `id`, `name`, `is_default`, created/updated timestamps;
- `research_run.runs`: existing lifecycle/provenance columns plus mutable `name`,
  `folder_id`, unique admission `request_id`, immutable input, and checksum;
- existing Attempt, cancellation, result-publication, and DailyTrack storage adjusted
  only as required by the new ownership rules.

Required constraints include exactly one Default Folder, every Run referencing a Folder,
unique accepted `request_id`, immutable input/checksum after insert, and no cascading
foreign key from ResearchRun to DailyTrack. DailyTrack retains a scalar seed Run ID and
complete origin snapshot, not a live Run dependency.

Delete, rather than migrate or retain:

- `src/thesistrace/definition/` and `src/thesistrace/definition/schema.sql`;
- Definition schema registration and runtime construction;
- Definition/revision columns embedded in ResearchRun projections and input;
- Definition run receipts after idempotency moves onto accepted Runs;
- `rerun_of_id`, rerun receipts, rerun command/model/service/route;
- Alpha/operator Release IDs used only for language dispatch or authoring history.

Object deletion must follow ownership. Deleting a Research removes Run-owned result
objects only after proving no surviving DailyTrack needs them; the Track's origin and
continuation state are independent. Deleting a stopped Track removes only Track-owned
objects. Any shared immutable Data generation remains governed by its existing owner.

## Implementation sequence

Each stage must leave its new module testable through its final interface. Old shallow
tests are replaced when the new interface becomes authoritative; they are not layered on
as permanent duplicate contracts.

1. **Characterize retained invariants.** Pin current Dataset Head admission, immutable
   checksum, durable claim/Attempt, cancel, publication, and DailyTrack continuation
   behavior. Identify which existing tests remain valid independent of Definition.
2. **Deepen the Data and Alpha Language modules.** Introduce canonical Field Definition
   capabilities, Data Series reading, Formula compiler, diagnostics, composed catalog,
   self-contained builtins, and calibrated admission limits. Delete duplicate Kernel
   field maps and split operator metadata/dispatch when the new interfaces pass.
3. **Unify Series execution.** Add the transient postorder plan and route both batch and
   incremental Alpha evaluation through it. Prove numeric equivalence and bounded work
   before changing HTTP behavior.
4. **Cut over persistence and backend HTTP in one schema reset.** Add Folders and direct
   Run admission, mutable organization, terminal Research deletion, and stopped Track
   deletion. In the same cutover remove Definition and rerun schemas, models, runtime
   composition, and routes; do not dual-write.
5. **Cut over the web workspace.** Replace the Definitions route/page with Folder-aware
   Research authoring, CodeMirror, local Drafts, catalog help, diagnostics, direct Run,
   rename/move/delete, and Use as Draft. Remove Save, Refresh, Revision, Rerun, and all
   links to Definition.
6. **Close lifecycle independence.** Verify a DailyTrack stays usable after its seed
   Research is deleted, render deleted origin safely, and verify Track deletion cleans
   only Track-owned state.
7. **Delete obsolete code and run final acceptance.** Remove replaced tests, exports,
   docs references, dependencies, schemas, and dead UI. Run the complete development and
   production-image gates against a fresh database.

## Test matrix

| Layer | Failure risk | Required observable tests |
| --- | --- | --- |
| Compiler unit | Python syntax accidentally expands the DSL. | Accept every documented form; reject statements/end-of-input junk, attribute/subscript, call chains, lambdas, collections, comprehensions, booleans/comparisons, conditional/walrus, keyword/star args, unsupported operators, and every non-allowlisted AST node. Assert stable code and exact range. |
| Compiler unit | Identifier or static type confusion. | Unknown name, field called as builtin, builtin used bare, duplicate cross-catalog identifier, invalid `snake_case`, scalar-only root, Series/Number broadcasting, Window only in declared positions, non-integer/out-of-range Window, bool/non-finite literal. |
| Compiler unit | Resource exhaustion. | Boundary and one-over tests for source length, AST node count, depth, 252-session effective lookback, and calibrated work budget. Large rejected input must not recurse, allocate a plan, or touch persistence. |
| Builtin contract | Metadata and evaluator drift apart. | Parameterize over every `BuiltinDefinition`: public projection, arity/types, lookback, work estimate, missing/numeric policy, deterministic vector result, and examples compile. Adding a builtin changes only its definition plus behavior fixtures. |
| Data architecture | Fields leak into Kernel/frontend allowlists or violate PIT/grain. | Catalog derives only from typed capabilities; internal fields stay absent; duplicate identifiers fail readiness; canonical ID resolution and units/availability are correct; architecture scan forbids Kernel canonical-key maps and frontend field lists. |
| Series evaluator | Nested expressions recompute or batch/track diverge. | Fixed-seed golden cases for nested arithmetic/builtins, scalar broadcasting, missing values, zero division, warmup, alignment, each plan node once, and exact batch versus session-by-session incremental equivalence. |
| Performance benchmark | A valid expression monopolizes a Worker. | Fixed dataset/universe/date range measures compile time, plan nodes, peak memory, and evaluation wall time. Check the committed ceiling and fail on a material regression; never use network data. |
| PostgreSQL integration | Folder and admission invariants race. | Fresh schema creates exactly one Default Folder; custom create/rename; Default and nonempty delete conflicts; concurrent same `request_id` yields one Run; same key/different payload conflicts; invalid admission creates no row/receipt/job. Use real isolated PostgreSQL. |
| PostgreSQL integration | Mutable metadata corrupts provenance. | Rename/move leaves immutable input bytes/checksum/result unchanged; duplicate names succeed; every Run retains a valid Folder; compiled Expression and field bindings cannot update. |
| PostgreSQL integration | Deletion cascades incorrectly. | Queued/running Research delete conflicts; each terminal state deletes; DailyTrack and complete origin survive seed Research deletion; deleted seed has no live FK; active/blocked Track delete conflicts; stopped Track delete removes Track-owned rows/objects only. |
| Worker integration | Worker trusts current Formula/catalog instead of admitted input. | Mutate source/catalog fixtures after admission and prove the claim executes the stored Expression; architecture test forbids source compilation in Worker; existing Attempt, retry, crash recovery, duplicate claim, cancel, and publication idempotency remain green. |
| HTTP contract | Preview and Run disagree or mutate on failure. | Diagnostics returns `200 {valid:false}` with ranges; Run returns the same diagnostic code/range as `422`; accepted Run returns `202`; no DB mutation on rejection; admission/cancel/PATCH/DELETE idempotency and `409` state conflicts; removed Definition/rerun endpoints return `404`. |
| Frontend unit | Draft behavior violates user expectations. | One storage key per Folder; missing means empty; no latest-Run restoration; Run retains content and updates executed baseline; New and Use as Draft confirm only over unexecuted changes; explicit Use as Draft copies frozen input; custom and Default Folder targeting; duplicate names render with distinguishing metadata. |
| Frontend unit | Stale async diagnostics overwrite current text. | Debounced requests cancel/ignore stale responses; ranges bind to the submitted source; network failure does not mark Formula valid; Run always sends current full Draft to the server. |
| Browser E2E | Core product journey is broken. | Global New -> Default Folder -> formula completion/diagnostic -> successful Research; create custom Folder -> Run; rename and move Research; refresh restores that Folder's local Draft; New starts empty after confirmation; Use as Draft -> edit -> Run; no Save/Refresh/Revision/Rerun/Definitions UI. |
| Browser E2E | Deletion and Track independence are misleading. | Cancel then delete Research; start Track from succeeded Research, stop Track, delete seed Research, reopen surviving Track with deleted-origin text, then delete stopped Track. Capture screenshots and request/response diagnostics on failure. |
| Production image smoke | Source-only tests miss packaging/schema/runtime errors. | Build final images, start a fresh isolated stack, apply the new schema, verify readiness, catalog, Folder, Run -> Worker -> result, Track start/stop/delete, and absence of obsolete endpoints. |

## Verification gates

Use the repository's root script names as the stable verification interface; the
implementation runner must invoke them through the repository-approved JS/Python runtime
at that time:

- `test`: static checks, deterministic unit/architecture/data tests, web typecheck and
  shell tests;
- `test:integration`: real isolated database/worker integration;
- `test:e2e`: full-stack browser acceptance;
- `check`: test + integration + E2E;
- `test:image-smoke`: final production-image smoke;
- `check:release`: complete release gate.

No test may depend on public network, wall-clock timing, arbitrary sleep, shared mutable
state, or retry-to-green behavior. Failures must retain relevant logs, HTTP payloads,
Trace IDs, seed, and browser screenshots.

## Acceptance criteria

- A user can create or select a Folder, write `ts_mean(close_adj, 20)`, click Run, and
  receive one queued Research without Save or Revision.
- Invalid Formula text receives source-ranged backend diagnostics and creates no durable
  state.
- A new capable Data field or builtin appears in compiler resolution and frontend help
  from one code-owned definition, with no second allowlist.
- The Worker executes only the admitted compiled Expression through the shared Series
  evaluator.
- Browser Draft behavior exactly matches the one-per-Folder, empty-by-default,
  no-auto-restore, Run-retains, explicit-Use-as-Draft rules.
- Research can be renamed or moved without changing provenance; names may duplicate.
- Only terminal Research is deletable, and deleting it never deletes or breaks its
  DailyTrack.
- Only stopped DailyTrack is deletable.
- Definition, Revision, Save, Refresh, Rerun, `rerun_of_id`, and obsolete endpoints,
  schemas, runtime composition, UI, and tests are absent from the final tree.
- `check:release` passes against the final production images and a fresh database, then
  real in-app-browser acceptance confirms the visible flow.

## Explicit non-goals

- user-defined functions, Python execution, statements, local variables, or plugins;
- Alpha Release IDs, multi-version language dispatch, or behavior-changing reuse of an
  existing identifier;
- cross-device/server Drafts, collaborative editing, autosaved server revisions;
- nested Folders, tags, saved searches, marketplace releases, or team merge semantics;
- product-level Rerun or implicit restoration from Research history;
- backward-compatible endpoints, dual schemas, migrations, backfills, or fallbacks;
- categorical/boolean Alpha values, intraday Alpha, arbitrary joins, or a general VM.

## References

- [`CONTEXT.md`](../../CONTEXT.md)
- [Compile Formula at Run admission](../../docs/adr/0157-compile-alpha-formulas-when-a-run-is-admitted.md)
- [Separate field and builtin ownership](../../docs/adr/0158-separate-alpha-field-and-builtin-ownership.md)
- [One append-only Alpha Language](../../docs/adr/0159-evolve-one-alpha-language-additively.md)
- [Strict Python AST subset](../../docs/adr/0167-parse-formulas-with-a-strict-python-ast-subset.md)
- [DSL editor as the only authoring surface](../../docs/adr/0168-make-the-dsl-editor-the-only-alpha-authoring-surface.md)
- [Explicit Data-owned Alpha Field Capability](../../docs/adr/0169-require-an-explicit-data-owned-alpha-field-capability.md)
- [One-level Research Folders and browser Drafts](../../docs/adr/0171-organize-runs-in-one-level-research-folders.md)
- [Mutable organization outside immutable Run input](../../docs/adr/0172-separate-research-organization-from-run-input.md)
- [Terminal Research deletion without Track cascade](../../docs/adr/0173-delete-only-terminal-research-without-cascading-tracks.md)
- [Stopped-only DailyTrack deletion](../../docs/adr/0174-delete-only-stopped-daily-tracks.md)
- [Reuse only through Use as Draft](../../docs/adr/0182-reuse-research-only-through-use-as-draft.md)
- [CodeMirror autocompletion module](https://github.com/codemirror/autocomplete)
- [CodeMirror lint module](https://github.com/codemirror/lint)

## Comments

- Design decisions were confirmed one at a time through Q1-Q24. This file is the frozen
  implementation specification; implementation issue generation remains a separate
  approval step.
