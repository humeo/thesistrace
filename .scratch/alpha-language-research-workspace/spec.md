# Alpha Formula Language and Research Workspace

**Status:** ready-for-agent

## Problem Statement

The current authoring experience exposes ThesisTrace's internal persistence model to
the user. A researcher has to think in terms of a saved Research Definition, Revision,
Save, Refresh, Run, and Rerun even though their actual goal is much simpler: write an
Alpha Formula, run it, and inspect the result. The current root-only Alpha builder also
prevents researchers from composing nested expressions naturally.

Alpha fields and operators are maintained in several places across Data, the Research
Kernel, and the frontend. Metadata, validation, physical field bindings, and execution
can drift. Adding a field or function therefore requires coordinated edits and makes it
hard to prove point-in-time safety, numeric behavior, missing-value behavior, lookback,
cost, and documentation from one source of truth.

ResearchRun history is durable but is presented as a flat list. As the number of Runs
grows, users need simple organization without introducing another durable Research
container. At the same time, ordinary editing is not a durable research event and
should not create server revisions or database traffic.

Deletion and reuse must also match the product model. A user should be able to reuse a
historical Run only through an explicit local Draft action, delete only completed
Research, and keep an independently running DailyTrack even after its seed Research is
deleted.

## Solution

ThesisTrace will provide one formula-first Research workspace. A user selects a
one-level Research Folder, edits one browser-local Draft, writes a single Alpha Formula,
and clicks Run. The backend authoritatively compiles and admits that complete Draft. A
rejected submission returns source-ranged diagnostics and creates no durable state; an
accepted submission atomically creates one ResearchRun with a frozen Formula,
ThesisTrace Alpha Expression, research parameters, calculation contracts, and data
admission facts.

Research Folders organize ResearchRuns only. One system-owned Default Folder receives
Research started from the global New action, while users may create and name custom
Folders. Every Folder has at most one browser-local Draft. Drafts are empty when absent,
survive refresh in the same browser, remain after Run, never restore from Run history
automatically, and can be replaced from history only through an explicit Use as Draft
action.

The Alpha Language will be a small, safe, expression-only DSL using bare identifiers
such as `close_adj` and calls such as `ts_mean(close_adj, 20)`. Data owns which canonical
fields are Alpha-authorable and how their Series are read. The Research Kernel owns
builtin definitions and Series evaluation. One composed authoring catalog drives the
compiler and frontend help without duplicating allowlists.

The frontend calls a ResearchRun a Research. ResearchRun remains the durable history,
while Research name and Folder membership are mutable organizational metadata outside
the immutable input. Product-level Rerun is removed; reuse is Use as Draft followed by
ordinary Run. Research and DailyTrack deletion are independent explicit actions.

## User Stories

1. As an individual quantitative researcher, I want to write one Alpha Formula and click Run, so that the product matches my research intent instead of exposing persistence mechanics.
2. As an individual quantitative researcher, I want field references without a `$` prefix, so that formulas are concise and familiar.
3. As an individual quantitative researcher, I want to compose nested builtin calls and arithmetic, so that I can express useful factors beyond a single root operator.
4. As an individual quantitative researcher, I want parentheses and numeric literals, so that I can control precedence and parameterize formulas clearly.
5. As an individual quantitative researcher, I want autocomplete for available fields and builtins, so that I can discover valid Alpha capabilities while typing.
6. As an individual quantitative researcher, I want inline documentation and examples for builtins, so that I can understand their parameters and semantics without leaving the editor.
7. As an individual quantitative researcher, I want source-ranged diagnostics while editing, so that I can find and correct a formula error quickly.
8. As an individual quantitative researcher, I want Run to validate the exact current Formula again, so that stale preview results cannot admit invalid research.
9. As an individual quantitative researcher, I want invalid research to create no Run or other server record, so that my history contains only research events I actually started.
10. As an individual quantitative researcher, I want the editor to remain usable when preview diagnostics are temporarily unavailable, so that a transient request failure does not destroy my local work.
11. As an individual quantitative researcher, I want the backend to remain the only diagnostic authority, so that browser and Worker behavior cannot disagree about language validity.
12. As an individual quantitative researcher, I want formulas to have deterministic numeric and missing-value semantics, so that the same admitted input produces the same Alpha Values.
13. As an individual quantitative researcher, I want expensive or pathologically deep formulas rejected before execution, so that one request cannot monopolize research capacity.
14. As an individual quantitative researcher, I want one Draft per Folder in my browser, so that each research area can retain its own current work.
15. As an individual quantitative researcher, I want a Folder with no local Draft to open empty, so that the product never surprises me with a historical Formula.
16. As an individual quantitative researcher, I want refreshing or reopening the browser to restore that Folder's local Draft, so that accidental navigation does not lose my work.
17. As an individual quantitative researcher, I want Run to leave my Draft unchanged, so that I can inspect or refine exactly what I submitted.
18. As an individual quantitative researcher, I want edits made while a Run request is pending to remain marked unexecuted, so that a successful earlier snapshot does not hide newer local changes.
19. As an individual quantitative researcher, I want New to clear the selected Folder's Draft explicitly, so that starting over is deliberate.
20. As an individual quantitative researcher, I want confirmation before New overwrites unexecuted changes, so that I do not discard local work accidentally.
21. As an individual quantitative researcher, I want Use as Draft to copy a selected Run's frozen authorable input, so that I can reproduce or modify historical research deliberately.
22. As an individual quantitative researcher, I want confirmation before Use as Draft overwrites unexecuted changes, so that historical reuse cannot silently replace my current work.
23. As an individual quantitative researcher, I want the product never to infer a Draft from my latest Run, so that Run history and local editing remain separate concepts.
24. As an individual quantitative researcher, I want to create and name a custom Research Folder, so that a large Run history is manageable.
25. As an individual quantitative researcher, I want global New Research to use one Default Folder, so that I can start immediately without creating organization first.
26. As an individual quantitative researcher, I want to start Research directly inside a selected custom Folder, so that new history appears where I expect it.
27. As an individual quantitative researcher, I want to rename a custom Folder, so that organization can evolve without changing Research results.
28. As an individual quantitative researcher, I want the Default Folder protected from deletion, so that the global creation path always has a valid destination.
29. As an individual quantitative researcher, I want deletion of a nonempty Folder rejected, so that organizing history never cascades into data loss.
30. As an individual quantitative researcher, I want Research Folders to remain one level deep, so that organization stays simple and predictable.
31. As an individual quantitative researcher, I want to optionally name a Research before Run, so that the resulting history is recognizable.
32. As an individual quantitative researcher, I want an unnamed accepted Research to receive a useful generated name, so that every list item remains understandable.
33. As an individual quantitative researcher, I want duplicate Research names allowed, so that naming does not become an execution constraint.
34. As an individual quantitative researcher, I want creation time, status, and Formula summary beside a Research name, so that similarly named Runs remain distinguishable.
35. As an individual quantitative researcher, I want to rename or move Research after execution, so that I can reorganize history without rerunning it.
36. As an individual quantitative researcher, I want rename and move to leave immutable input, provenance, and results unchanged, so that organization cannot alter scientific evidence.
37. As an individual quantitative researcher, I want each Run to freeze its admitted Formula and compiled Alpha Expression, so that the Worker executes the exact accepted research.
38. As an individual quantitative researcher, I want infrastructure retry to remain under the same ResearchRun as an Attempt, so that operational recovery does not create false research history.
39. As an individual quantitative researcher, I want product-level Rerun removed, so that every reused idea passes through an inspectable Draft and ordinary Run.
40. As an individual quantitative researcher, I want to cancel queued or running Research explicitly, so that deletion never doubles as cancellation.
41. As an individual quantitative researcher, I want to delete only succeeded, failed, or cancelled Research, so that active execution cannot race permanent deletion.
42. As an individual quantitative researcher, I want Research deletion to remove only Research-owned state, so that unrelated durable resources remain intact.
43. As an individual quantitative researcher, I want a DailyTrack to continue after its seed Research is deleted, so that forward tracking remains an independent product resource.
44. As an individual quantitative researcher, I want a surviving DailyTrack to show the deleted seed Run ID as provenance rather than a broken link, so that its origin remains understandable.
45. As an individual quantitative researcher, I want to delete a DailyTrack only after stopping it, so that deletion cannot race active or blocked progression work.
46. As an individual quantitative researcher, I want stopped DailyTrack deletion to remove its owned checkpoints, progressions, caches, and receipts, so that explicit deletion is complete.
47. As an Alpha platform maintainer, I want a canonical field to require an explicit typed Alpha capability, so that existence in Data does not automatically expose it to research.
48. As an Alpha platform maintainer, I want Data to own point-in-time meaning, grain, unit, availability, missingness, and Series reading, so that Alpha fields cannot bypass data contracts.
49. As an Alpha platform maintainer, I want one stable Alpha Identifier per authorable field or builtin, so that formulas remain readable and additively extensible.
50. As an Alpha platform maintainer, I want field and builtin identifiers checked in one global namespace, so that catalog composition detects collisions before readiness.
51. As an Alpha platform maintainer, I want each builtin's signature, documentation, lookback, missingness, numeric behavior, evaluator, and cost estimate defined together, so that metadata and execution cannot drift.
52. As an Alpha platform maintainer, I want adding a capable field or builtin to update compiler resolution and frontend help automatically, so that extension does not require duplicated allowlists.
53. As an Alpha platform maintainer, I want one append-only Alpha Language with no Release ID dispatcher, so that compatibility is maintained by stable identifiers rather than runtime version routing.
54. As an Alpha platform maintainer, I want behaviorally different functionality to receive a new identifier, so that an existing Formula never silently changes meaning.
55. As an Alpha Research Kernel maintainer, I want a transient postorder Series Execution Plan, so that every expression node is computed once without persisting an execution VM.
56. As an Alpha Research Kernel maintainer, I want ResearchRun and DailyTrack to share the same Series evaluator, so that batch and incremental results stay canonically equivalent.
57. As an Alpha security maintainer, I want Python parsing used only behind an exhaustive expression allowlist, so that Formula text can never invoke arbitrary Python behavior.
58. As an Alpha security maintainer, I want Python AST discarded before persistence and execution, so that no Python code object or interpreter capability crosses the Alpha Language interface.
59. As an operator, I want accepted Run creation to be idempotent under request retries, so that duplicate delivery creates one ResearchRun.
60. As an operator, I want malformed or rejected Run requests to leave no receipt, row, or queue work, so that cleanup and capacity accounting remain reliable.
61. As an operator, I want work limits calibrated against a representative fixed benchmark, so that admission limits reflect measured capacity rather than arbitrary configuration.
62. As an operator, I want the production image smoke test to exercise the final schema and Worker path, so that packaging and startup failures are caught before release.

## Implementation Decisions

### Domain model and lifecycle

- The product has Browser Draft, Research Folder, ResearchRun, ResearchRun Attempt, and
  DailyTrack. It no longer has a server-saved Research Definition or visible Revision.
- The frontend calls a ResearchRun a Research. There is no intermediate durable Research
  container.
- A Research Folder is one-level organization only. It stores no Formula, Draft,
  parameters, execution state, or Revision.
- Every ResearchRun belongs to exactly one Folder. One deterministic system-owned
  Default Folder always exists, cannot be renamed or deleted, and receives global New
  Research.
- Custom Folder names are mutable. A custom Folder may be deleted only when empty; Folder
  deletion never moves or deletes Research.
- Research name and `folder_id` are mutable organization metadata outside immutable Run
  input. Names are optional, non-unique, and blank names become `Research <short-run-id>`.
- A Research list shows name, creation time, status, and a short Formula summary. Run ID
  remains identity.
- Run is the only ordinary server-persisting authoring action. Save, Refresh, Revision,
  and product-level Rerun are removed.
- ResearchRun retains `queued`, `running`, `succeeded`, `failed`, and `cancelled` states.
  Infrastructure retries remain Attempts under the same Run.
- Only terminal Research can be deleted. Delete does not cancel work.
- DailyTrack remains independently durable after seed Research deletion because it owns
  a complete Tracking Origin snapshot and only retains the seed Run ID as provenance.
- Only a stopped DailyTrack can be deleted. Stop remains a separate explicit action for
  active or blocked Tracks.

### Browser Draft and interaction

- Draft is browser-only state with exactly one Draft per Folder. It has no server ID,
  audit authority, revision, or synchronization contract.
- The current bounded Draft payload uses localStorage. It includes prospective Research
  name, Formula, Hypothesis, requested dates, Universe, neutralization, Strategy
  parameters, cursor/editor state, and the last admitted local baseline.
- Absence of the Folder's local key means an empty Draft. The frontend never pulls the
  latest Run to initialize it.
- Run submits the complete current Draft but does not clear or replace it.
- The executed baseline is the exact submitted snapshot accepted by the server. Edits
  made while admission is pending remain unexecuted.
- New explicitly clears the current Folder Draft. Use as Draft explicitly replaces its
  authorable values from a selected Run. Neither action makes a server request that
  creates a resource.
- New and Use as Draft require confirmation only when they would overwrite unexecuted
  local changes.
- Use as Draft copies frozen authorable input, not mutable Research name or Folder
  membership. The target remains the Folder whose Draft the user is editing.
- Cross-device Draft continuity is deferred. A future requirement introduces a separate
  Draft Resource rather than changing Folder or ResearchRun.
- CodeMirror 6 is the editor adapter for completion, help, and ranged diagnostics. The
  frontend does not implement a second authoritative parser or type checker.
- Preview diagnostics are debounced and stale responses are ignored. Run always sends
  the current full Draft and the backend compiles it again.

### Alpha Language

- An Alpha Formula contains exactly one expression followed by end of input.
- The grammar permits bare field identifiers, numeric literals, parentheses, unary
  minus, binary addition/subtraction/multiplication/division, and positional builtin
  calls.
- The grammar excludes statements, assignment, variables, control flow, imports,
  attributes, indexing, collections, comprehensions, boolean/comparison expressions,
  conditional expressions, keyword or starred arguments, and user-defined functions.
- Fields and builtins expose stable lowercase `snake_case` Alpha Identifiers in one
  globally unique namespace. Field references do not use `$` or another prefix.
- The static value model is Numeric Series, Number, and Window. Window is accepted only
  in declared builtin positions, and the Formula root must be Numeric Series.
- The current effective-lookback maximum remains 252 Research Sessions. Window literals
  remain integers from 1 through 252.
- There is one current append-only Alpha Language. There is no persisted or user-visible
  Alpha Release ID, operator release, or multi-version dispatcher.
- Once published, an identifier retains its meaning. Behaviorally different semantics
  require a new identifier.
- Python's expression parser may be used internally only to obtain syntax positions. An
  exhaustive node/operator allowlist immediately converts accepted input to a
  ThesisTrace-owned immutable Alpha Expression.
- Python AST, code objects, and interpreter execution never cross the Alpha Language
  interface, enter persistence, or reach a Worker. Python `compile`, `eval`, and `exec`
  are prohibited for Formula handling.
- The compiler produces the Alpha Expression, resolved canonical field bindings, static
  result type, effective lookback, node/depth counts, and deterministic work estimate.
- Admission enforces fixed maximum source length, node count, nesting depth, effective
  lookback, and estimated work. Limits other than the already fixed lookback are chosen
  from a committed representative benchmark before the endpoint ships.

### Catalog ownership and extension

- A canonical Data field is not automatically an Alpha input. Its Data-owned Field
  Definition must explicitly contain an optional typed `AlphaFieldCapability`.
- The surrounding Field Definition remains the sole owner of canonical field ID,
  point-in-time meaning, instrument-by-Research-Session grain, physical type, unit,
  availability, and missingness.
- `AlphaFieldCapability` contains only the stable Alpha Identifier and current Alpha
  value type.
- Data owns the Series reader for capable fields. The Research Kernel and frontend do
  not maintain physical row-key maps or second field allowlists.
- The compiler resolves an Alpha Identifier to a stable canonical field ID. The compiled
  Field Reference stores the canonical ID, and evaluation requests Data Series by that
  ID.
- The Research Kernel owns one self-contained `BuiltinDefinition` for each builtin. It
  owns identifier, typed positional parameters, result rule, documentation, examples,
  lookback calculation, missing-value behavior, numeric behavior, evaluator, and work
  estimator.
- The Alpha Authoring Catalog is a read-only composition of Data field projections and
  builtin public projections. Application readiness fails on invalid or duplicate
  identifiers.
- The same catalog projection supplies compiler resolution and frontend completion/help;
  evaluator callables and physical storage facts remain private.
- Users cannot register fields, builtins, Python, UDFs, or plugins at runtime. Platform
  maintainers extend the language in reviewed code.

### Compile, admission, execution, and persistence

- Preview and Run use the same backend Alpha Language. Preview returns diagnostics only;
  Run authoritatively compiles before any durable mutation.
- Diagnostics have stable codes, human-readable messages, severity, and start/end source
  ranges. Syntax, unknown identifier, callability, arity, type, Window, non-finite
  literal, source size, node, depth, lookback, and work-budget failures are distinct.
- Rejected admission returns structured issues and creates no Run, idempotency record,
  queue item, or other durable resource.
- Accepted admission atomically creates one queued ResearchRun with its unique request
  ID and complete immutable input. Retrying the same key and payload returns the same
  Run; reusing the key with a different payload conflicts.
- Immutable Run input contains Formula source, compiled Alpha Expression, Hypothesis,
  requested dates, resolved field bindings, Universe, neutralization, Strategy
  parameters, costs, risk-free rate, numeric/calculation contracts, and required Dataset
  Head or generation admission facts.
- Research name, Folder membership, lifecycle state, timestamps, Attempts, failure
  summary, and result pointers remain outside immutable input.
- The Worker executes only the stored ThesisTrace Alpha Expression. It never recompiles
  Formula source or reads Draft/Folder state.
- Evaluation builds a transient postorder Series Execution Plan and computes each node
  once. The plan is not a persisted VM or public resource.
- ResearchRun batch calculation and DailyTrack incremental advancement use the same
  Series evaluator and retain canonical batch-incremental equivalence.
- The fresh PostgreSQL schema introduces Research Folders and moves accepted admission
  idempotency onto ResearchRun. It removes Definition/revision persistence, Definition
  run receipts, rerun ancestry, rerun receipts, and product rerun commands.
- This development-stage cutover uses a fresh schema reset. It includes no migration,
  backfill, dual-write, compatibility endpoint, fallback parser, feature flag, or old/new
  runtime switch.
- Final code contains only the new authoring and Run path. Obsolete routes, models,
  schemas, runtime composition, frontend controls, links, and duplicate tests are
  deleted rather than retained.

### HTTP contracts

- `GET /api/alpha/catalog` returns authorable field and builtin projections.
- `POST /api/alpha/diagnostics` is non-mutating and returns `200` with validity and
  diagnostics for a well-shaped request. Request-shape errors return `422`.
- `GET /api/research-folders`, `POST /api/research-folders`,
  `PATCH /api/research-folders/{folder_id}`, and
  `DELETE /api/research-folders/{folder_id}` expose one-level Folder management.
- `POST /api/research-runs` admits a complete Draft directly. Acceptance returns `202`;
  Formula or admission rejection returns `422` and no durable mutation.
- `GET /api/research-runs` supports Folder filtering and cursor pagination.
- `GET /api/research-runs/{run_id}` includes the frozen authorable input required by Use
  as Draft and the existing result detail.
- `PATCH /api/research-runs/{run_id}` changes only Research name and Folder membership.
- `POST /api/research-runs/{run_id}/cancel` retains idempotent cancellation.
- `DELETE /api/research-runs/{run_id}` enforces terminal-only Research deletion.
- `POST /api/research-runs/{run_id}/daily-tracks` retains explicit Track creation from a
  successful Research.
- Existing DailyTrack list, detail, retry, and stop contracts remain.
- `DELETE /api/daily-tracks/{track_id}` enforces stopped-only Track deletion.
- Definition CRUD/run and ResearchRun rerun endpoints do not exist in the final HTTP
  interface.

### Deletion ownership

- Research deletion removes the Research resource, Attempts, accepted-request record,
  results, and Research-owned artifacts only when no surviving durable resource needs a
  physical object.
- Research deletion never deletes or mutates DailyTrack. A surviving Track retains its
  copied Tracking Origin, seed Run ID, continuation state, and results.
- Track deletion removes the stopped Track and Track-owned progressions, Attempts,
  checkpoints, working caches, receipts, and unreferenced Track-owned objects.
- Shared immutable Data generations remain governed by Data ownership and are never
  deleted as a side effect of Research or Track deletion.

## Testing Decisions

- Tests assert observable behavior at a module interface and do not depend on private
  parser helpers, internal plan nodes, SQL call counts, or frontend implementation
  details. When a new deep module interface becomes authoritative, obsolete shallow
  tests are replaced rather than retained as a second contract.
- The primary backend acceptance seam is direct ResearchRun admission through the HTTP
  interface, followed through durable claim, Worker execution, publication, and public
  result. This is the highest existing seam that covers the core product invariant.
- The primary user acceptance seam is the real browser journey across Folder selection,
  Formula editing, diagnostics, Run, history, Use as Draft, deletion, and DailyTrack.
- Pure Alpha Language tests cover every accepted grammar form and reject every
  non-allowlisted Python AST family, unsupported operator, trailing input, invalid
  identifier, callability error, arity error, type error, invalid Window, non-finite
  literal, and scalar root. They assert stable diagnostic codes and exact source ranges.
- Compiler resource tests exercise each admission limit at the boundary and one beyond
  it. Rejection must occur before plan construction or persistence.
- Catalog contract tests parameterize every builtin and capable field. They prove public
  projection, static types, lookback, work estimate, examples, missing/numeric behavior,
  canonical field resolution, and readiness failure on identifier collision.
- Architecture tests prove there is no Kernel physical-key map, frontend field allowlist,
  Worker Formula compilation, Python execution primitive, Definition route, or product
  rerun route in the final runtime.
- Series evaluator tests use fixed deterministic data to cover nested expressions,
  scalar broadcasting, missing values, invalid logarithm, zero division, warmup,
  alignment, and deterministic numeric semantics.
- Batch-incremental equivalence tests execute the same admitted Expression and inputs as
  one ResearchRun batch and session-by-session DailyTrack advancement, then compare
  canonical retained results exactly.
- A fixed representative benchmark records compile time, plan size, peak memory, and
  evaluation wall time for the maximum supported universe/date shape. It sets admission
  limits and fails on a material performance regression.
- PostgreSQL integration tests use a real isolated database. They cover exactly one
  Default Folder, Folder create/rename/delete guards, Run/Folder constraints, duplicate
  names, concurrent identical admission, idempotency-key payload conflict, and absence
  of durable rows after rejection.
- Persistence tests prove rename and move do not change immutable input bytes, checksum,
  provenance, or result, and prove compiled Expression and field bindings cannot be
  updated.
- Lifecycle integration tests cover successful, invalid, unauthorized where applicable,
  duplicate, concurrent, cancel, retry, crash-recovery, and partial-publication cases.
- Research deletion tests cover queued/running conflict and deletion from each terminal
  state. They prove DailyTrack and its complete origin remain usable after seed deletion.
- DailyTrack deletion tests cover active/blocked conflict, explicit Stop, deletion of a
  stopped Track, owned-state cleanup, and preservation of unrelated Research/Data state.
- HTTP contract tests prove preview/Run diagnostic parity, preview's non-mutating `200`,
  Run rejection's `422`, accepted Run's `202`, mutation conflicts' `409`, and obsolete
  endpoints' `404`.
- Frontend tests cover one local Draft per Folder, empty-on-absence, no latest-Run
  restoration, Run retention, exact admitted baseline, pending-edit behavior, New and
  Use as Draft confirmations, duplicate names, Folder targeting, and stale diagnostic
  response suppression.
- Browser E2E covers global New in Default Folder, custom Folder creation, completion and
  diagnostics, successful Research, rename/move, refresh recovery, explicit New, Use as
  Draft followed by another Run, cancellation/deletion, Track creation, seed Research
  deletion, Track survival, Stop, and Track deletion.
- Browser acceptance explicitly proves Save, Refresh, Revision, Rerun, and Definitions
  UI are absent. Failures retain screenshots, requests/responses, status, logs, and Trace
  IDs.
- Production-image smoke starts a fresh isolated stack and schema, then verifies
  readiness, catalog, Folder, Run-to-Worker-to-result, Track start/stop/delete, and
  absence of obsolete endpoints against the final images.
- Tests use fixed time, timezone, UUIDs, random seed, and fixtures; no public network,
  execution-order dependency, arbitrary sleep, shared mutable state, or retry-to-green
  behavior is permitted.
- Existing prior art to retain includes kernel expression contracts, Dataset Head
  admission tests, durable ResearchRun claim/retry/cancel acceptance tests, schema
  lifecycle integration tests, DailyTrack persistence/equivalence tests, page shell
  tests, and the full browser research loop. Definition-specific and product-rerun tests
  are replaced.
- The final feature gate is the complete release check against a fresh database and
  production images, followed by real in-app-browser acceptance. Passing source-only
  tests is not sufficient.

## Out of Scope

- User-defined functions, user Python, SQL, imports, statements, variables, control
  flow, or runtime plugins.
- Alpha Release IDs, multiple active language versions, operator-version dispatch, or
  behavior-changing reuse of an existing identifier.
- Server Drafts, cross-device Draft synchronization, collaborative editing, merge
  conflict handling, or server autosave.
- Nested Folders, tags, saved searches, marketplaces, published strategy releases, or
  team permissions.
- Product-level Rerun, implicit latest-Run restoration, or automatic Run creation from
  Use as Draft.
- Backward-compatible Definition endpoints, compatibility schemas, migrations,
  backfills, dual-write, fallback parsing, or feature-flagged old/new paths.
- Boolean or categorical Alpha value types, intraday Alpha, arbitrary joins, a general
  bytecode VM, or persisted execution plans.
- Runtime user registration of fields or builtins.
- Changes to established Strategy, Factor Evaluation, Dataset Head, Numeric Execution,
  publication, or DailyTrack progression semantics except where explicitly required for
  the new authoring and deletion lifecycle.
- Hosted identity, tenancy, billing, quotas beyond existing DailyTrack limits, or
  cross-user Folder sharing.

## Further Notes

- This specification intentionally supersedes the Research Definition, visible
  Revision, Run-saves-Definition, and product-level Rerun portions of ADR-0095,
  ADR-0151, ADR-0154, and the older Definition lifecycle decisions. Their persistent
  ResearchRun state, Attempt, Dataset Head selection, publication, and DailyTrack
  invariants remain in force.
- The matching Alpha Language, catalog ownership, browser Draft, Folder, deletion, and
  Use as Draft ADR decisions were confirmed individually during Q1-Q24 and are treated
  as frozen inputs to implementation.
- No Alpha Release ID is required because published identifiers and semantics evolve
  additively. This does not remove independent calculation-contract identifiers that
  remain necessary for existing Strategy, Factor, or Numeric provenance.
- The implementation should be delivered in vertical stages, but the final runtime must
  contain one path only: characterize retained invariants; build Data/Alpha Language;
  unify Series execution; hard-cut backend schema and HTTP; hard-cut the browser
  workspace; verify deletion independence; remove obsolete code; run the release gate.
- Implementation issue generation remains a separate `to-tickets` approval step. This
  spec is fully triaged as `ready-for-agent`, but no implementation ticket is created by
  this step.

## Comments

- Synthesized from the Q1-Q24 design decisions and published with `to-spec`. No business
  code was changed by this step.
