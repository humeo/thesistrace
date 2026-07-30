Status: ready-for-agent

# ThesisTrace Bounded Research Storage

## Problem Statement

ThesisTrace must preserve reproducible Factor Evaluation, Strategy Backtest,
and Daily Tracking conclusions without retaining every calculation
intermediate. The current fixture representation stores growing
instrument-by-session and event data as nested JSON, so a small three-year,
30-stock fixture already occupies far more space than a production
ResearchRun can afford. Scaling that shape to thousands of instruments,
hundreds of Research Sessions, many ResearchRuns, and continuous DailyTracks
would make storage, serialization, object validation, and incremental updates
unnecessarily expensive.

A successful ResearchRun needs a small immutable Result Bundle that can render
the confirmed report and seed a DailyTrack. Daily Tracking needs enough
short-lived state to append one new Research Session without replaying from its
Tracking Origin, but that state must remain bounded, disposable, and unable to
replace immutable Checkpoint truth. Physical Data Objects also need a
deterministic byte identity so checksums, deduplication, publication limits, and
reproduction have one unambiguous meaning.

## Solution

Publish only bounded, user-visible conclusions and continuation state.
Manifests, configuration, provenance, and summaries remain canonical JSON.
Retained data whose size grows with Research Sessions, instruments, or event
count uses ZSTD-compressed Parquet. Alpha Matrix values, stock-level Forward
Return Labels, daily Factor observations, raw orders, fills, and rejection
details remain execution intermediates and are absent after successful
publication.

Every successful ResearchRun atomically publishes a complete Result Bundle
whose exact ResearchRun-owned bytes do not exceed `1,048,576`. The bundle keeps
bounded Factor summaries, the complete Strategy Daily Observation table,
bounded Strategy aggregates, Terminal Positions, and Terminal Strategy State;
it keeps no Factor curves. A production-writer capacity gate proves this limit
using the same deterministic Parquet contract as the application.

Each active DailyTrack incrementally advances from its Tracking Head and may
use one latest-only Working Cache in a shared `WorkingCacheStore`. On the
controlled single-node deployment, this store is a named volume shared by the
Compute Workers; it is neither the immutable Object Store nor a Worker's
private scratch directory. Each cache is bound to authoritative identities and
a fencing token, contains at most 21 pending Alpha sessions and 1,512 rolling
Factor rows, and may occupy at most `2,097,152` exact bytes. Missing, stale,
oversized, or inconsistent cache content is discarded and rebuilt over only
the bounded required windows. Stopping a DailyTrack deletes its cache, and a
stale Worker can never publish or resurrect an older cache.

Immutable Parquet Physical Data Objects use the SHA-256 digest of their exact
bytes as identity. A versioned deterministic writer contract fixes schema,
column order, row order, one row group per Physical Data Object in V1, writer
and Parquet versions, ZSTD version and level, and all encoding options. A
writer upgrade creates a new writer-contract identifier rather than silently
changing the bytes produced under an existing contract.

## User Stories

1. As a research author, I want every successful ResearchRun to remain below a precise storage limit, so that running more research does not produce unbounded private storage growth.
2. As a research author, I want a Result Bundle to retain the conclusions visible in my Factor and Strategy report, so that storage optimization does not remove the report I requested.
3. As a research author, I want the complete Strategy Daily Observation series retained, so that cumulative return, risk, cost, exposure, and execution metrics remain derivable.
4. As a research author, I want bounded Factor summaries for all 1-, 5-, and 20-session horizons, so that I can judge an Alpha without storing its daily Factor history.
5. As a research author, I want no daily Factor curves retained or displayed, so that a compact set of stability statistics replaces a large time series I do not need.
6. As a research author, I want Alpha Matrix values removed after successful calculation, so that instrument-by-session intermediates do not become permanent result data.
7. As a research author, I want stock-level Forward Return Labels removed after their aggregates are calculated, so that labels do not duplicate reproducible inputs and calculations.
8. As a research author, I want raw orders and fills removed after Strategy results are finalized, so that the result stores conclusions rather than an unnecessary execution ledger.
9. As a research author, I want rejection details reduced to the confirmed daily and period aggregates, so that the report keeps useful rejection evidence without storing every event.
10. As a research author, I want Terminal Positions and Terminal Strategy State retained, so that a successful ResearchRun can seed a DailyTrack without reconstructing its ending account.
11. As a research author, I want bounded rebalance and execution aggregates retained, so that the confirmed Strategy metrics remain explainable without raw event history.
12. As a research author, I want a Run to fail publication rather than silently omit required results when its bundle exceeds the limit, so that every succeeded Run satisfies one complete contract.
13. As a research author, I want failed and cancelled Runs to publish no partial Result Bundle, so that a visible result is never mistaken for complete truth.
14. As an operator, I want the one-MiB limit measured from the exact bytes of every ResearchRun-owned manifest and payload, so that compression, deduplication, and accounting cannot hide an oversized bundle.
15. As an operator, I want shared Dataset Release objects excluded from a ResearchRun's private budget, so that shared platform data is not charged repeatedly to each result.
16. As an operator, I want content-addressed deduplication to leave the logical per-Run budget unchanged, so that two Runs referencing identical bytes cannot bypass the contract.
17. As an operator, I want manifests, configuration, provenance, and bounded summaries stored as canonical JSON, so that small control records remain inspectable and deterministic.
18. As an operator, I want retained growing tabular data stored as ZSTD Parquet, so that repeated field names and nested JSON materialization do not dominate storage or reads.
19. As an operator, I want each bounded ResearchRun table stored as one Parquet object rather than one object per Research Session, so that file overhead does not consume the one-MiB budget.
20. As an operator, I want Physical Data Object identities derived from exact immutable bytes, so that verification and deduplication use the same identity.
21. As an operator, I want the Parquet writer contract version recorded with every immutable Parquet object, so that its bytes can be reproduced by the correct writer.
22. As an operator, I want the writer contract to fix schema and column order, so that logically equivalent tables cannot hash differently because of incidental field ordering.
23. As an operator, I want the writer contract to fix canonical row order, so that source iteration and Worker scheduling cannot change an object's identity.
24. As an operator, I want V1 to write one row group per Physical Data Object, so that row-group boundaries cannot vary across executions.
25. As an operator, I want the writer, Parquet, ZSTD, and encoding options pinned, so that dependency upgrades cannot silently alter content-addressed identities.
26. As an operator, I want any writer-contract upgrade to use a new identifier, so that old and new bytes are never claimed to follow the same contract.
27. As a research author, I want a DailyTrack to process only Research Sessions after its current Tracking Checkpoint, so that adding one new session does not replay the complete history.
28. As a research author, I want each new Alpha calculation to read its complete bounded Canonical input window, so that incremental execution preserves the Alpha's numeric semantics.
29. As a research author, I want pending Alpha Values kept only until their longest Label horizon matures, so that Daily Tracking can resolve Labels without retaining permanent Alpha history.
30. As a research author, I want at most 21 pending Alpha signal sessions in the Working Cache, so that the cache remains independent of the DailyTrack's age.
31. As a research author, I want rolling Factor observations limited to the latest 504 signal sessions for three horizons, so that summary calculation uses at most 1,512 aggregate rows.
32. As a research author, I want mature stock-level Labels discarded after the daily Factor aggregate is produced, so that Tracking does not create a growing Label store.
33. As a research author, I want Factor Summary Snapshots published in immutable Tracking Checkpoints, so that the latest visible conclusion does not depend on mutable cache content.
34. As a research author, I want Strategy Daily Observation and bounded aggregate deltas published by each successful Tracking Advance, so that continuous Strategy history remains authoritative and queryable.
35. As a research author, I want Terminal Strategy State published by every successful Tracking Advance, so that the next Advance can continue from immutable state.
36. As an operator, I want a Working Cache created only for a DailyTrack, so that ordinary ResearchRuns do not pay for unused Tracking state.
37. As an operator, I want active DailyTracks admitted under the Active DailyTrack Limit, so that the controlled node has a bounded number of live caches and Advances.
38. As an operator, I want the WorkingCacheStore shared by Compute Workers on the controlled node, so that a retry on another Worker can use the current bounded cache.
39. As an operator, I want the WorkingCacheStore separated from the immutable Object Store, so that mutable optimization state cannot be presented as Result or Checkpoint truth.
40. As an operator, I want the WorkingCacheStore separated from Worker scratch, so that Worker replacement does not unnecessarily destroy the only current cache copy.
41. As an operator, I want each DailyTrack cache capped at `2,097,152` exact bytes, so that row bounds and compression do not leave byte growth unspecified.
42. As an operator, I want a cache that exceeds its byte budget rejected and rebuilt or the Advance failed without moving Tracking Head, so that no successful operation violates the cache bound.
43. As an operator, I want every cache bound to its DailyTrack, Generation, basis Checkpoint, Definition hash, calculation-kernel version, Numeric Execution Contract, and basis Dataset Release, so that incompatible state is never reused.
44. As an operator, I want cache payload identities recorded in the basis record, so that partial or corrupt cache contents are detected before use.
45. As an operator, I want a monotonic fencing token on cache publication, so that a delayed Worker cannot replace a newer cache after losing ownership of an Advance.
46. As an operator, I want temporary cache payloads committed atomically before the basis record, so that interruption cannot expose a partially updated cache as valid.
47. As an operator, I want a missing or mismatched cache discarded automatically, so that cache recovery does not require manual repair.
48. As an operator, I want cache reconstruction limited to the pending-Alpha and latest-504 Factor windows, so that recovery cost remains bounded rather than growing with Tracking history.
49. As an operator, I want a Worker restart to recover from immutable Checkpoints and ordered Dataset Releases, so that mutable cache loss cannot destroy research truth.
50. As an operator, I want stopping a DailyTrack to trigger retryable Working Cache deletion, so that a crash cannot leave stopped-Track storage outside active quotas.
51. As an operator, I want a stopped DailyTrack's former cache namespace fenced permanently, so that an old Worker cannot recreate storage for a terminal Track.
52. As a research author, I want accepted historical data corrections to continue in the same Tracking Generation, so that a data correction does not trigger a costly historical replay.
53. As a research author, I want correction-boundary results to use the ordered Dataset Release sequence recorded by the Checkpoint chain, so that the as-operated Track remains reproducible.
54. As a research author, I want previously published observations and state preserved across a historical correction, so that immutable research history is never rewritten.
55. As a research author, I want only a result-changing calculation-kernel correction to build a new Tracking Generation, so that data correction and runtime semantic correction remain distinct.
56. As a platform developer, I want deterministic Parquet identity tests to pass in fresh processes, so that hidden process state cannot affect immutable object bytes.
57. As a platform developer, I want the production writer used by capacity tests, so that prototype-specific encodings cannot provide false storage confidence.
58. As a platform developer, I want two-Worker failure tests around WorkingCacheStore ownership, so that retries, crashes, and stale commits cannot corrupt the latest cache.
59. As an operator, I want cache failures to leave the last successful Tracking Checkpoint and Head unchanged, so that an operational optimization cannot cause partial product state.
60. As an operator, I want development fixture JSON artifacts to be disposable, so that the greenfield implementation can adopt the production boundary without a migration subsystem.

## Implementation Decisions

- Result publication is atomic. A ResearchRun becomes `succeeded` only after its
  Result Manifest and every referenced object are complete, checksummed, and
  within the exact `1,048,576`-byte ResearchRun-owned budget.
- ResearchRun-owned bytes include all manifests and payloads owned by that Run.
  Shared Dataset Release objects do not count. Deduplication affects physical
  occupancy but does not reduce the logical byte total assigned to a Run.
- A Result Bundle contains canonical JSON provenance, Result Manifest, three
  bounded Factor Evaluation summaries, and one bounded Strategy summary. It
  also contains ZSTD Parquet Strategy Daily Observations, rebalance aggregates,
  execution aggregates, Terminal Positions, plus bounded Terminal Strategy
  State in the smallest appropriate JSON or Parquet representation.
- Strategy Daily Observations are retained completely for the Research Window
  because they are the authoritative source for confirmed Strategy series and
  derived metrics. Cash Ratio and Drawdown remain derived rather than duplicate
  stored series.
- Alpha Matrix values, stock-level Forward Return Labels, daily Factor
  observations, Five-Quantile curves, Top-Bottom curves, target-weight history,
  raw orders, child orders, fills, rejection-event details, and other
  calculation diagnostics are transient. They must not be referenced by a
  successful Result Manifest or Tracking Checkpoint.
- Factor Evaluation calculates daily observations in canonical signal-session
  order only long enough to produce per-horizon bounded summaries. The product
  neither persists nor displays Factor curves.
- Small manifests, configuration, provenance, cache basis records, and bounded
  summaries use canonical JSON. Retained tables that grow by Research Session,
  instrument, or event count use Parquet with ZSTD compression.
- Each bounded table in one ResearchRun is written as one Parquet Physical Data
  Object. Canonical Dataset Family partitioning remains a separate Dataset
  Release concern and is not copied into a Result Bundle.
- Immutable Parquet Physical Data Object identity is the lowercase SHA-256
  digest of the exact object bytes. Manifest checksum and content-addressed
  object identity use this same byte sequence.
- Every immutable Parquet object records a writer-contract identifier. The
  contract pins the explicit schema, column order, canonical row sort keys,
  null and logical-type representation, one row group per Physical Data Object
  for V1, concrete writer and Parquet versions, concrete ZSTD version and
  compression level, and every encoding option that can affect bytes.
- Writers must reject input that cannot be canonically ordered under the
  object's declared contract. Runtime map iteration, source response order,
  thread scheduling, and process locale must not affect output bytes.
- A dependency or option upgrade that can change Parquet bytes requires a new
  writer-contract identifier. Existing Physical Data Objects retain their old
  identity and remain readable under the contract recorded in their manifest.
- The production Parquet writer is the sole implementation used by publication
  and storage-capacity acceptance. The prototype remains evidence for the
  design but is not a second production writer.
- A normal Tracking Advance computes only the Research Sessions added after its
  basis Tracking Checkpoint. It reads Canonical lookback data from Dataset
  Releases and never copies the maximum 252-session Alpha lookback into its
  Working Cache.
- `WorkingCacheStore` is an explicit mutable operational-storage interface. In
  the controlled single-node deployment it is backed by one named volume
  mounted read-write by the Compute Workers. It is not implemented by the
  immutable Object Store and is not located in a Worker's private scratch.
- There is one latest-only Working Cache namespace per active DailyTrack. It
  contains a canonical JSON basis record, up to 21 signal-session Pending Alpha
  Parquet partitions ordered by `instrument_id`, and one Rolling Factor
  Observation Parquet object containing at most 504 sessions times three
  horizons, or 1,512 rows.
- The complete cache namespace for one DailyTrack, including basis, current
  payloads, and committed storage metadata, must not exceed `2,097,152` exact
  bytes. Temporary files are excluded only while an in-progress attempt owns
  them and must be removed after commit, failure, or recovery. An Advance never
  moves Tracking Head while the committed cache exceeds the budget.
- The authoritative execution coordinator grants each cache-writing Attempt a
  monotonically increasing fencing token associated with the DailyTrack and
  target Advance. `WorkingCacheStore` accepts a commit only when the token is
  current and the DailyTrack remains active. A later token permanently rejects
  an older Worker's commit, cleanup, or recreation request.
- The cache basis records DailyTrack identity, Tracking Generation, basis
  Tracking Checkpoint identity and checksum, Definition hash,
  calculation-kernel version, Numeric Execution Contract, basis Dataset
  Release, fencing token, and exact identities and sizes of current payloads.
- Cache writes stage payloads under attempt-scoped temporary names, validate
  row and byte limits, atomically install payloads, and atomically replace the
  basis record last. Readers accept a cache only when every basis coordinate,
  fencing token, payload identity, size, and row limit matches.
- Missing, corrupt, stale, or incompatible cache content is discarded. It is
  rebuilt from the immutable Activation and Checkpoint chain, its ordered
  Dataset Release sequence, and pinned research semantics, but only over the
  at-most-21-session Pending Alpha and latest-504-session Factor windows.
- A successful Advance publishes immutable Factor Summary Snapshots, new
  Strategy Daily Observations and bounded aggregate deltas, and Terminal
  Strategy State before atomically moving Tracking Head. Working Cache content
  is never authoritative Checkpoint content.
- A failed or interrupted Advance leaves Tracking Head unchanged. Its staged
  cache files are disposable, and its retry may reuse only a valid current
  cache or perform the bounded rebuild.
- Stopping a DailyTrack first advances the authoritative fencing state so no
  older Worker can commit, then terminally records `stopped` and durably queues
  idempotent deletion of the Track's Working Cache namespace. A stopped Track
  cannot recreate a cache or resume in V1; startup and scheduled reconciliation
  delete any cache namespace whose Track is absent or no longer active, so a
  crash after the stop commit cannot leave permanent orphan cache data.
- The Active DailyTrack Limit governs admission in both a V1 Workspace and a
  hosted Personal Workspace. A blocked active Track continues to count; a
  stopped Track does not. The cache byte budget is enforced independently per
  admitted Track.
- An accepted historical Dataset correction is applied prospectively by an
  ordinary Advance in the same Tracking Generation. The authoritative
  Checkpoint predecessor chain and each target Dataset Release define the exact
  ordered release sequence used to rebuild bounded cache observations.
- Historical corrections do not modify prior Factor Summary Snapshots,
  Strategy observations, Terminal Strategy State, or pending Strategy
  decisions. Only values first calculated at or after the correction boundary
  use the correcting Dataset Release.
- A result-changing calculation-kernel correction, not a historical data
  correction, creates a fully executed new Tracking Generation under the
  existing runtime-correction contract.
- Existing development fixture artifacts stored as nested JSON may be deleted
  and rebuilt under this contract. This is a greenfield boundary change and
  does not require a production-data migration path.

## Testing Decisions

- Tests assert behavior through published resource state, manifests, exact
  object bytes, checksums, report values, Tracking Head, and cache recovery
  outcomes. They do not assert internal helper calls, temporary filenames, or
  implementation-specific in-memory representations.
- The primary acceptance seam is the public application API for the complete
  lifecycle: create and run a frozen Research Definition, inspect the succeeded
  Result Bundle and rendered report, start a DailyTrack, publish later Dataset
  Releases, advance the Track, stop it, and inspect immutable Checkpoints and
  final cache absence.
- The lifecycle test verifies that one successful Result Manifest references
  every required JSON and Parquet object, references none of the forbidden
  transient artifacts, and reports an exact total no greater than
  `1,048,576` bytes.
- The lifecycle test independently derives all confirmed Factor summary and
  Strategy report values from the retained boundary. It verifies that no
  Factor curve endpoint or durable daily Factor series is exposed.
- An over-budget publication test uses otherwise valid required results whose
  production-writer bytes exceed `1,048,576`; it must fail atomically without a
  succeeded Run or partial Result Bundle.
- A production-writer capacity gate exercises the conservative model used by
  the existing storage-budget prototype: 756 Strategy sessions, daily
  rebalancing, and up to 3,000 Terminal Positions. It must use the actual
  production writer contract and stay within the ResearchRun budget.
- Deterministic Parquet identity tests write the same canonical table in fresh
  processes, with different source row and field insertion orders, and require
  byte-for-byte equality and the same SHA-256 identity.
- Writer-contract tests verify that schema, column order, canonical row order,
  row-group count, logical types, null behavior, Parquet version, ZSTD settings,
  and encoding options match the declared contract. A changed byte-affecting
  contract must have a different identifier.
- The existing storage-budget prototype is prior art for conservative data
  shapes, byte counting, metric reconstruction, and bounded Tracking cache
  sizing. Its fixture writer is not accepted as proof of production output.
- A two-Worker failure seam runs two real Compute Worker processes against the
  shared WorkingCacheStore and authoritative execution coordinator. It pauses
  Worker A after staging, grants Worker B a newer fencing token, lets Worker B
  complete, then proves Worker A cannot commit, delete, or resurrect its stale
  cache.
- Cache acceptance tests verify the at-most-21 Pending Alpha session limit, the
  at-most-1,512 Rolling Factor row limit, and the complete
  `2,097,152`-byte committed namespace limit independently.
- Cache corruption tests cover a missing basis, missing payload, wrong payload
  checksum, wrong Definition hash, wrong Generation, wrong basis Checkpoint,
  wrong Dataset Release, wrong numeric or kernel contract, excess rows, and
  excess bytes. Each case discards the cache and performs only a bounded
  rebuild before publishing equivalent results.
- Restart tests kill a Worker after payload staging, after payload installation,
  and before basis replacement. A later Worker must either accept a fully
  consistent cache or discard it; Tracking Head and immutable Checkpoints must
  never reflect partial work.
- Stop tests race a DailyTrack stop with an in-flight Worker. They verify that
  the authoritative stop wins, the cache is deleted, the stale Worker remains
  fenced, no new Checkpoint is published after the stop boundary, and the
  stopped Track no longer consumes an active-Track quota slot.
- Stop-cleanup recovery tests interrupt execution after the authoritative
  `stopped` commit but before cache deletion, then restart reconciliation and
  require the orphan namespace to be removed idempotently without changing the
  immutable Head or allowing a stale Worker to recreate it.
- Historical-correction tests execute the same ordered Dataset Release sequence
  in the reference oracle and incremental Track. They verify continuation in
  the same Generation, unchanged prior observations, bounded cache rebuild,
  visible correction provenance, and canonical exact results at each accepted
  boundary.
- Kernel-correction tests verify the opposite boundary: a declared
  result-changing calculation-kernel correction creates a new fully executed
  Tracking Generation and does not mutate the prior Generation.
- Batch-Incremental Equivalence is tested explicitly rather than rerun during
  every normal Advance. Runtime Alpha Values, Labels, orders, and fills may be
  instrumented inside this test only and must be absent from persistent product
  storage after completion.

## Out of Scope

- Choosing or migrating the physical encoding of accepted Tushare source raw
  evidence.
- Persisting Alpha Matrix values, stock-level Forward Return Labels, daily
  Factor observations or curves, target-weight history, raw orders, child
  orders, fills, detailed rejection events, or an execution-debugging ledger.
- Showing Factor curves in the Web UI or introducing a general-purpose
  historical Factor observation query API.
- Moving the controlled single-node WorkingCacheStore to a distributed cache
  service, supporting multi-node shared-filesystem semantics, or providing
  cross-region cache replication.
- Treating Working Cache content as an immutable Physical Data Object,
  Result Bundle object, Tracking Checkpoint payload, provenance record, or
  backup-critical product truth.
- Full-history replay for ordinary Tracking Advances or historical Dataset
  corrections.
- Migrating existing production Result Bundles, Tracking Checkpoints, or
  fixture JSON artifacts. The project is greenfield; development fixtures may
  be rebuilt.
- Changing Alpha, Label, Factor, Strategy, execution, cost, Dataset Release, or
  correction semantics except where required to define their retained storage
  boundary.
- Adding notifications, live trading, user-selectable storage formats, storage
  pricing, or a general artifact-download product.

## Further Notes

- The existing prototype measured a conservative ResearchRun at 335,168 bytes
  with one ZSTD Parquet object per bounded table, while one Parquet object per
  session exceeded seven MiB. This supports the chosen table-level Result
  Bundle layout but must be repeated with the production writer.
- The same prototype measured a Top3000 Working Cache at approximately
  1.28 MiB for 21 Pending Alpha partitions, 1,512 Factor rows, and the basis
  record. The `2,097,152`-byte hard limit preserves measured headroom while
  making the formerly implicit byte bound explicit.
- The maximum 252-session Effective Alpha Lookback remains in shared Dataset
  Release data and affects calculation reads, not Working Cache retention.
- JSON remains appropriate for bounded control records; Parquet is selected by
  growth shape rather than applied indiscriminately to every artifact.
- This spec consolidates the accepted storage direction in ADR-0102,
  ADR-0103, ADR-0105, ADR-0108, ADR-0144, ADR-0146, ADR-0147, and ADR-0148.
  ADR-0146 and ADR-0148 now record the aligned immutable Parquet byte identity,
  shared WorkingCacheStore, byte cap, fencing, and cleanup decisions.
