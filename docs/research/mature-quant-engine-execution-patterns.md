# Mature Quant Engine Execution Patterns for Long-Horizon Research

Date: 2026-08-17

## Decision boundary

This note investigates how mature open-source quantitative engines execute long
histories, dynamic universes, rolling formulas, cross-sectional factors, and
stateful backtests without making memory proportional to every intermediate
value in the entire run.

It is comparative research, not a decision to adopt any one engine or its data
format. ThesisTrace remains a module-first PostgreSQL/RustFS system and does not
introduce Qlib, LEAN, Zipline, Backtrader, NautilusTrader, or vectorbt as a new
runtime dependency.

Only first-party material is used below: official documentation, official
repositories, and the original Qlib paper.

## Executive conclusion

The mature systems do **not** converge on one universal execution model. They
converge on a separation of responsibilities:

1. **Historical feature computation** uses bounded date ranges, explicit
   lookback extension, field selection, masks for the actual daily universe,
   and early release of dead intermediate values. Qlib and Zipline provide the
   clearest examples.
2. **Trading simulation** advances a compact mutable account/portfolio state
   through an ordered event stream. LEAN and NautilusTrader provide the clearest
   examples; Qlib's backtest loop follows the same broad pattern.
3. **Rolling state** is bounded by the indicator window, not by total history.
   LEAN's `RollingWindow` and Backtrader's `exactbars` make this explicit.
4. **Dynamic universe state** is created when a security enters and removed
   when it exits. It is not safe to allocate every expression node over the
   Cartesian product of all dates and the full-period security union.
5. **Results are a separate concern from computation.** Mature engines either
   send deltas, retain bounded presentation samples, or write experiment
   artifacts. A long-lived Worker should not keep all UI/report objects in its
   computation heap.

For ThesisTrace, the most appropriate synthesis is:

```text
Qlib / Zipline:
  formula DAG + effective lookback + date chunks + per-session universe mask

LEAN / NautilusTrader:
  ordered session stream + bounded rolling state + persistent portfolio state

ThesisTrace-specific:
  Arrow/Parquet projection + online Factor aggregation + immutable result
  partitions + resumable chunk checkpoint + atomic final Result publication
```

This is stronger than merely increasing the current work limit or wrapping the
existing Python dictionaries in a time loop. The current full-history Python
object graph must cease to be the execution representation.

This synthesis reinforces, rather than replaces, four accepted ThesisTrace
decisions:

- [ADR-0131](../adr/0131-preserve-top-3000-with-bounded-memory-columnar-execution.md)
  already requires bounded-memory columnar execution for Top 3000.
- [ADR-0164](../adr/0164-evaluate-alpha-as-a-series-execution-plan.md)
  already requires one transient post-order plan and one-pass rolling builtins.
- [ADR-0102](../adr/0102-make-batch-versus-incremental-equivalence-the-v1-end-to-end-goal.md)
  makes batch/incremental equivalence the correctness target.
- [ADR-0146](../adr/0146-store-growing-tabular-data-as-partitioned-parquet.md)
  already chooses partitioned Parquet for growing tables and transient Alpha,
  Label, and daily Factor values.

The implementation should therefore complete the existing design, not add a
parallel engine or a second versioned runtime.

## Comparison at a glance

| Engine | Long-history mechanism | Rolling/window mechanism | Dynamic/cross-sectional universe | Stateful simulation | Memory/result boundary |
| --- | --- | --- | --- | --- | --- |
| Microsoft Qlib | Range queries over per-instrument/per-field storage; expression and dataset caches | Operators calculate required extended windows; Pandas/Cython rolling | Instrument date ranges and DataFrame processors; `CSRankNorm` groups by date | Trade-calendar loop updates decisions, account, and position state | Bounded memory cache is configurable, but handlers still materialize Pandas DataFrames |
| QuantConnect LEAN | One ordered `TimeSlice` at a time | Fixed-size `RollingWindow` ring buffer and finite warm-up | Universe changes add/remove security-specific state | Event-driven algorithm, portfolio, broker, and execution state | Result handling is separate and incremental; old security state must be removed |
| Zipline-reloaded | `run_chunked_pipeline` executes date chunks | Execution plan requests extra rows for each term | Lifetimes matrix plus daily Pipeline screen/mask | Separate event-driven algorithm simulator | DAG values are reference-counted and released, but public chunk API concatenates final chunks in memory |
| Backtrader | Feed-by-feed `next()` mode, or faster preloaded batch mode | `exactbars` bounds each line by its minimum required period | Primarily explicit feeds rather than a first-class cross-sectional factor engine | Broker and strategy advance one bar at a time | Clear speed/memory tradeoff: bounded buffers disable preload/run-once and plotting |
| NautilusTrader | Parquet catalog with automatic or manual streaming batches | Incremental indicators and engine/cache state | Subscription-driven event model; not primarily a cross-sectional research engine | A single engine continues across batches with `run(streaming=True)` | `clear_data()` releases consumed batches while strategy/portfolio state remains alive |
| vectorbt | Dense NumPy arrays and compiled kernels | Vectorized array operations | Masks and broadcasting over dense shapes | Compiled traversal/callback simulation | Extremely fast for dense arrays, but array/broadcast shape remains the fundamental memory domain |

## 1. Microsoft Qlib

### What it does well

Qlib separates raw data access, formulaic expressions, handler processing, and
model-specific datasets. Its official data documentation describes basic data
stored in a finance-oriented binary format, formula features built by an
expression engine, higher-level processors in `DataHandler`, and time segments
in `Dataset` ([Qlib Data Layer](https://qlib.readthedocs.io/en/latest/component/data.html)).
The original paper describes the storage, expression, cache, and parallel data
processing design ([Qlib paper](https://arxiv.org/abs/2009.11189)).

Relevant patterns are:

- Basic data is organized by instrument and field, so a request can select a
  date range and only the required fields rather than decode unrelated tables.
- Rolling operators calculate their necessary extended window. `Rolling` and
  `Ref` expose the longest backward window and left/right extension, and use
  optimized Pandas rolling operations rather than a Python nested loop
  ([official `ops.py`](https://github.com/microsoft/qlib/blob/main/qlib/data/ops.py)).
- Expression and dataset caches are disk-backed options, while the global
  memory cache accepts a size/length limit
  ([official cache documentation](https://qlib.readthedocs.io/en/latest/component/data.html#cache)).
- Cross-sectional ranking is explicitly a per-date operation:
  `CSRankNorm` groups a DataFrame by `datetime` and then ranks across stocks
  ([official `processor.py`](https://github.com/microsoft/qlib/blob/main/qlib/data/dataset/processor.py)).
- Qlib's backtest is not a vectorized reconstruction of the account on every
  date. Its loop generates a trade decision, lets the executor collect/execute
  it, updates account and position state, and advances the trade calendar
  ([official `backtest.py`](https://github.com/microsoft/qlib/blob/main/qlib/backtest/backtest.py),
  [official `executor.py`](https://github.com/microsoft/qlib/blob/main/qlib/backtest/executor.py)).
- Recorder tracks parameters, metrics, statuses, and artifacts such as
  predictions or model checkpoints
  ([official Recorder documentation](https://qlib.readthedocs.io/en/latest/component/recorder.html)).

### What ThesisTrace should not copy

Qlib's current public handler/dataset path still centers on Pandas DataFrames.
`DataHandlerLP` can retain raw, inference, and learning frames; its own memory
tip is `drop_raw=True` so processing can modify the raw frame in place
([Qlib Data Layer, DataHandlerLP](https://qlib.readthedocs.io/en/latest/component/data.html#datahandlerlp)).
That is useful for model research but is not an Arrow-first bounded-streaming
contract for a long Top 3000 product run.

Likewise, Recorder artifact persistence is experiment management. A recorder
that can be resumed is not evidence that arbitrary mid-backtest continuation
state is automatically checkpointed. ThesisTrace needs an explicit computation
checkpoint contract of its own.

### Applicable lesson

Derive `effective_lookback` from the formula DAG before loading data. Read only
the requested chunk plus that finite left overlap. Calculate a cross-sectional
operator only after all valid members for one session are present. Do not split
one day's `rank` into unrelated security shards.

## 2. QuantConnect LEAN

### What it does well

LEAN's main algorithm loop consumes a synchronized stream one `TimeSlice` at a
time. Each slice carries the data and security changes for the current frontier;
the loop applies universe changes, updates the algorithm, emits transactions and
results, and checks cancellation rather than constructing a full-history
matrix ([official `AlgorithmManager.cs`](https://github.com/QuantConnect/Lean/blob/master/Engine/AlgorithmManager.cs),
[official `TimeSliceFactory.cs`](https://github.com/QuantConnect/Lean/blob/master/Engine/DataFeeds/TimeSliceFactory.cs)).

Its rolling window is a fixed-size FIFO. The documentation explicitly says that
updating a `RollingWindow` with the newest point is more efficient than making
repeated history requests
([official Rolling Window documentation](https://www.quantconnect.com/docs/v2/writing-algorithms/historical-data/rolling-window)).
The implementation uses a preallocated list and overwrites the tail when full
([official `RollingWindow.cs`](https://github.com/QuantConnect/Lean/blob/master/Common/Indicators/RollingWindow.cs)).

LEAN also makes the dynamic-security lifecycle explicit:

- Universe changes are delivered to `OnSecuritiesChanged`, allowing state to be
  created and destroyed with membership
  ([official Universe documentation](https://www.quantconnect.com/docs/v2/writing-algorithms/universes/key-concepts)).
- Indicators for dynamically selected securities should be created/warmed when
  securities enter and deregistered when they leave
  ([official Indicator Universes documentation](https://www.quantconnect.com/docs/v2/writing-algorithms/indicators/indicator-universes)).
- The consolidator documentation warns that failing to remove consolidators for
  departed securities makes the algorithm progressively slower and can exhaust
  RAM
  ([official consolidator documentation](https://www.quantconnect.com/docs/v2/writing-algorithms/consolidating-data/consolidator-types/count-consolidators)).

Warm-up replays only the required history into the same algorithm state. The
official documentation also warns that warm-up over many assets can be slow,
which argues against requesting full history again at every block boundary
([official Warm Up documentation](https://www.quantconnect.com/docs/v2/writing-algorithms/historical-data/warm-up-periods)).

Finally, result handling is outside the algorithm hot loop. The backtesting
result handler processes updates on a separate path, periodically stores result
snapshots, and bounds/resamples presentation data for long runs
([official `BacktestingResultHandler.cs`](https://github.com/QuantConnect/Lean/blob/master/Engine/Results/BacktestingResultHandler.cs)).

### What ThesisTrace should not claim

LEAN's Object Store is a general key-value persistence surface for strings,
JSON, XML, bytes, and files. The documentation recommends saving a backtest's
data at the end and permits more frequent saves in live trading
([official Object Store documentation](https://www.quantconnect.com/docs/v2/writing-algorithms/object-store)).
That does not prove that a normal LEAN backtest can automatically restart from
an arbitrary `TimeSlice`. Its result snapshots are also not computation
continuation checkpoints.

### Applicable lesson

Strategy execution should be one ordered session state machine. Cash,
positions, pending orders, transaction-cost accumulators, and rolling metrics
are the continuation state. Cancellation should be checked at least at each
chunk boundary, and preferably at cheap session boundaries. Security-specific
state must be released when it can no longer affect positions, orders, or
required lookback.

## 3. Zipline / zipline-reloaded

### What it does well

Zipline's Pipeline engine provides the closest direct precedent for a
date-chunked cross-sectional factor engine. `run_chunked_pipeline` divides the
requested date range by `chunksize`; its public contract states that chunking
reduces memory and may reduce computation time
([official API](https://zipline.ml4trading.io/api-reference.html#zipline.pipeline.engine.PipelineEngine.run_chunked_pipeline),
[official engine source](https://zipline.ml4trading.io/_modules/zipline/pipeline/engine.html)).

For each chunk, the engine:

- Builds an execution plan with extra input rows for rolling terms.
- Constructs an asset-lifetimes Boolean matrix and removes assets that did not
  exist anywhere in that chunk.
- Applies the Pipeline screen so output contains only the `(date, asset)` pairs
  admitted on each date.
- Topologically computes expression terms in a workspace.
- Reference-counts dependencies and deletes a term as soon as no later node
  needs it.

These behaviors are described in the
[official Pipeline Engine algorithm](https://zipline.ml4trading.io/api-reference.html#pipeline-engine)
and implemented in the
[official engine source](https://zipline.ml4trading.io/_modules/zipline/pipeline/engine.html).
Windowed terms receive extra rows; `CustomFactor` receives only assets allowed
by its daily mask, and factors such as rank operate row-wise across the accepted
assets
([official Factor source](https://zipline.ml4trading.io/_modules/zipline/pipeline/factors/factor.html),
[official Term source](https://zipline.ml4trading.io/_modules/zipline/pipeline/term.html)).

### Important limitation

The public `run_chunked_pipeline` implementation collects each chunk DataFrame
in a Python list and concatenates them at the end. It bounds intermediate
Pipeline computation, but the final returned result still grows with the total
run ([official implementation](https://zipline.ml4trading.io/_modules/zipline/pipeline/engine.html)).

### Applicable lesson

Copy the execution-plan, overlap, daily mask, and dependency-lifetime ideas.
Do **not** copy the list-then-concatenate result boundary. ThesisTrace should
write each completed result partition to immutable storage, keep only bounded
aggregators in memory, and publish the final manifest after all partitions pass
validation.

## 4. Backtrader

Backtrader exposes the speed/memory tradeoff in a particularly understandable
form. Its default `preload=True, runonce=True` path preloads feeds and executes
indicators in batch for speed
([official operating documentation](https://www.backtrader.com/docu/operating/)).

Its `exactbars=1` memory-saving mode instead shrinks every line buffer to the
automatically calculated minimum period. A 30-period moving average therefore
keeps a running buffer of 30 bars. This mode disables preload, vectorized
run-once execution, and plotting
([official memory-saving documentation](https://www.backtrader.com/docu/memory-savings/memory-savings/)).

This is evidence for two ThesisTrace rules:

1. A bounded rolling buffer is a legitimate semantic execution model, not an
   approximation of full history.
2. Bounded memory alone does not guarantee speed. Falling back from compiled or
   columnar batch execution to Python bar-by-bar callbacks can trade OOM for a
   very slow run.

Backtrader is less useful as a model for Top 3000 cross-sectional factor
evaluation because its core abstraction is a collection of feeds and lines,
not a daily masked factor DAG over a large changing equity universe.

## 5. NautilusTrader

NautilusTrader combines a persistent columnar catalog with a stateful streaming
engine. Its `ParquetDataCatalog` stores market data in Parquet and uses a Rust
query backend for core types plus PyArrow for custom types and advanced filters
([official Data documentation](https://nautilustrader.io/docs/latest/concepts/data/)).

For data that does not fit in memory, the official backtesting guide supports:

```python
for batch in data_batches:
    engine.add_data(batch)
    engine.run(streaming=True)
    engine.clear_data()

engine.end()
```

`run(streaming=True)` pauses when the current data is exhausted without
finalizing the trader; `clear_data()` removes the consumed batch; `end()` flushes
timers and produces final results. The high-level `BacktestNode` automates
catalog chunking and exposes a configurable `chunk_size`
([official Backtest API documentation](https://nautilustrader.io/docs/latest/concepts/backtesting/apis-and-runs/)).

This is the strongest direct precedent for keeping one strategy/portfolio state
alive while replacing the input batch. The engine also shares its core data,
cache, message bus, portfolio, and execution concepts across backtest, sandbox,
and live contexts
([official Architecture documentation](https://nautilustrader.io/docs/latest/concepts/architecture/),
[official execution flow](https://nautilustrader.io/docs/latest/concepts/backtesting/execution-flow/)).

NautilusTrader is primarily an event/execution engine, not a large-equity
cross-sectional factor planner. ThesisTrace should borrow its streaming
continuation boundary, not substitute its object event model for Arrow-based
factor calculation.

## 6. vectorbt as the dense-vectorized contrast

vectorbt represents strategies and records with structured NumPy arrays and
uses compiled kernels for very high throughput. Its official documentation
supports both vectorized arrays and callback-driven portfolio simulation
([official feature overview](https://vectorbt.dev/getting-started/features/),
[official Portfolio API](https://vectorbt.dev/api/portfolio/base/)).

It reduces avoidable expansion by retaining original broadcast shapes and using
flexible indexing. Its own indicator documentation nevertheless warns that
broadcasting many parameters to an input shape can consume substantial memory
when the array materializes
([official IndicatorFactory documentation](https://vectorbt.dev/api/indicators/factory/)).

This is a useful performance reference for small or naturally dense matrices
and parameter sweeps. It is not the right primary model for ThesisTrace's
maximum case: 2010-to-latest, Top 3000, point-in-time membership, financial
fields, daily cross-sectional ranking, and immutable result publication. That
case needs sparse admission plus bounded time chunks, not one permanent dense
array for every node and every security ever admitted.

## 7. Recommended ThesisTrace execution model

### 7.1 One planner, two execution modes inside one implementation

Do not create a V2 engine or preserve the current dense path as a fallback.
Replace the current representation behind one `ResearchExecution` boundary:

```text
ResearchExecution.execute(immutable_input, generation) -> PreparedResult
```

Internally, the plan has two coordinated stages:

```text
Parquet projection
  -> date chunk + left lookback + right label horizon
  -> Alpha DAG over Arrow arrays
  -> daily Universe mask
  -> daily cross-sectional operators
  -> Factor online aggregators
  -> session-ordered Strategy state machine
  -> immutable Result partition
  -> checkpoint
```

The caller should not configure chunk size or know whether a node is rolling,
cross-sectional, or stateful.

### 7.2 Apply it to the failing formula

For:

```text
rank(pct_change(close, 20))
```

the planner should:

1. Compile one DAG and derive a 20-session left lookback.
2. Select only sessions, instrument identity, point-in-time universe
   eligibility, `close_adj`, and fields required by Factor/Strategy execution.
3. Read a bounded date chunk plus the 20 preceding sessions. Securities may
   need pre-admission price history to obtain a valid first in-universe value.
4. Calculate `pct_change` once per admitted instrument/session series.
5. For each official research session, apply `rank` to the complete valid
   Top 3000 membership for that session.
6. Feed Alpha observations and matured forward labels into online Factor
   accumulators rather than retaining a second full matrix.
7. Advance one portfolio state through the session stream.
8. Write the completed output partition, update the checkpoint, release the
   Arrow buffers, and continue.

The full-period union may be used for metadata discovery, but it must not define
the dense width of every execution node for every date.

### 7.3 Memory ownership

At any point, the Worker should own only:

- One projected Arrow chunk and its bounded overlap.
- Live DAG nodes whose consumers have not finished.
- The current session's cross-section.
- Bounded forward-label pending state.
- Online Factor accumulators.
- Strategy cash, holdings, pending orders, costs, and metric accumulators.
- Result objects not yet flushed into the current partition.

Each DAG node needs a consumer/reference count like Zipline's workspace. Once
the count reaches zero, release its buffers. Common subexpressions must be
computed once within the plan.

Start with a run-local chunk cache and common-subexpression reuse. Qlib proves
that expression/dataset caches can accelerate repeated research, but a durable
cross-run expression cache should be added only after measurement. If added,
its key must include the immutable generation, canonical formula/node,
projection, date bounds, and numeric contract.

### 7.4 Budget semantics

Replace one reject-or-accept work number with two independent quantities:

```text
estimated_total_work
  = sum(actual admitted cells per chunk * formula/operator cost)

estimated_peak_work
  = max(live cells and live bytes within one planned chunk)
```

- Total work controls queueing, estimated duration, progress, and possibly a
  user-visible warning. Long history alone should not be rejected.
- Peak work is the hard safety boundary. The planner reduces chunk size until
  the projected peak fits.
- Formula length, node count, maximum depth, and maximum lookback remain hard
  admission limits. Chunking does not make an unbounded expression safe.
- If even the minimum legal chunk cannot fit, reject it before starting.

This follows the distinction visible across Zipline/Nautilus chunking and
LEAN/Backtrader bounded state: total time can grow with history while peak
memory remains bounded.

### 7.5 Result persistence and recovery

None of the surveyed systems establishes ThesisTrace's exact requirement:
resume a product ResearchRun after Worker loss while preserving an immutable,
content-addressed Result contract. Implement this explicitly.

A checkpoint should bind at least:

```text
immutable_input_sha256
generation_manifest_sha256
execution_contract_sha256
completed_through_session
factor_aggregator_state
pending_forward_label_state
strategy_cash_positions_orders_and_cost_state
completed_result_partition_hashes
```

Rolling Alpha buffers do not necessarily need to be serialized: because input
data is immutable, the resumed chunk can reread the finite left overlap and
deterministically rebuild them. Persist the smaller state that cannot be
recovered from overlap, especially Factor aggregators and portfolio state.

Write a result partition first, verify its hash, and then atomically advance the
checkpoint reference. Publish the final immutable Result manifest only after
all partitions and summaries validate. Partial partitions remain private and
must never appear as a successful Result.

### 7.6 Cancellation and progress

LEAN demonstrates cheap cancellation checks at event-loop boundaries; the
chunked engines provide natural progress boundaries. ThesisTrace should:

- Check cancellation between chunks and at bounded session intervals.
- Emit stages and `completed_sessions / total_sessions` during loading, Alpha,
  Factor, Strategy, partition flush, and final validation.
- Never require the current multi-minute Python call to finish before observing
  cancellation.
- Retain diagnostic timing and peak-byte measurements per stage/chunk.

## 8. Delivery and acceptance order

Implement the replacement in this order, stopping to measure after every step:

1. Add a columnar date-range projection that does not call `to_pylist()` and
   does not construct a full-run dictionary.
2. Build an Alpha plan with derived overlap, common-subexpression reuse, and
   dependency lifetime release.
3. Execute point-in-time universe masks and cross-sectional operators by
   complete session.
4. Convert Factor calculations to bounded online aggregators.
5. Convert Strategy to one continuation state that survives input chunks.
6. Flush immutable result partitions and then add recovery checkpoints.
7. Replace the current total-work rejection with peak-chunk admission and
   total-work scheduling/progress.

Required equivalence and performance gates:

- `rank(pct_change(close, 20))`, Top 3000, 2010-to-latest completes
  without OOM.
- Peak resident memory is bounded by configured chunk size and does not grow
  linearly with additional years.
- Chunk sizes such as 21, 63, 252, and 504 sessions produce the same canonical
  Alpha, Factor, Strategy, and final Result checksums.
- Security entry/exit, suspension, delisting, industry changes, and financial
  point-in-time observability remain identical to the reference semantics.
- A process loss after a completed partition resumes from the checkpoint and
  produces the same final Result checksum as an uninterrupted run.
- Cancellation becomes terminal within a bounded interval and does not publish
  a partial Result.
- The final Production Image run records stage timings and peak RSS.

The surveyed engines do not support a defensible exact prediction such as
“2010-to-latest will finish in four minutes” for ThesisTrace's data and formula
contract. Set the time gate only after the first Arrow-first end-to-end
benchmark. The reliable conclusion from primary sources is architectural:
bounded peak memory and long total history are compatible, but only when the
execution representation, state lifetime, and result path are bounded together.

## Primary sources

### Microsoft Qlib

- [Qlib Data Layer](https://qlib.readthedocs.io/en/latest/component/data.html)
- [Qlib Recorder](https://qlib.readthedocs.io/en/latest/component/recorder.html)
- [Original Qlib paper](https://arxiv.org/abs/2009.11189)
- [`qlib/data/data.py`](https://github.com/microsoft/qlib/blob/main/qlib/data/data.py)
- [`qlib/data/ops.py`](https://github.com/microsoft/qlib/blob/main/qlib/data/ops.py)
- [`qlib/data/dataset/processor.py`](https://github.com/microsoft/qlib/blob/main/qlib/data/dataset/processor.py)
- [`qlib/backtest/backtest.py`](https://github.com/microsoft/qlib/blob/main/qlib/backtest/backtest.py)
- [`qlib/backtest/executor.py`](https://github.com/microsoft/qlib/blob/main/qlib/backtest/executor.py)

### QuantConnect LEAN

- [Rolling Window](https://www.quantconnect.com/docs/v2/writing-algorithms/historical-data/rolling-window)
- [Warm Up Periods](https://www.quantconnect.com/docs/v2/writing-algorithms/historical-data/warm-up-periods)
- [Universe key concepts](https://www.quantconnect.com/docs/v2/writing-algorithms/universes/key-concepts)
- [Indicators with dynamic universes](https://www.quantconnect.com/docs/v2/writing-algorithms/indicators/indicator-universes)
- [Count consolidators](https://www.quantconnect.com/docs/v2/writing-algorithms/consolidating-data/consolidator-types/count-consolidators)
- [Object Store](https://www.quantconnect.com/docs/v2/writing-algorithms/object-store)
- [`AlgorithmManager.cs`](https://github.com/QuantConnect/Lean/blob/master/Engine/AlgorithmManager.cs)
- [`TimeSliceFactory.cs`](https://github.com/QuantConnect/Lean/blob/master/Engine/DataFeeds/TimeSliceFactory.cs)
- [`RollingWindow.cs`](https://github.com/QuantConnect/Lean/blob/master/Common/Indicators/RollingWindow.cs)
- [`BacktestingResultHandler.cs`](https://github.com/QuantConnect/Lean/blob/master/Engine/Results/BacktestingResultHandler.cs)

### Zipline-reloaded

- [Pipeline Engine API](https://zipline.ml4trading.io/api-reference.html#pipeline-engine)
- [Pipeline Engine source](https://zipline.ml4trading.io/_modules/zipline/pipeline/engine.html)
- [Factor source](https://zipline.ml4trading.io/_modules/zipline/pipeline/factors/factor.html)
- [Term source](https://zipline.ml4trading.io/_modules/zipline/pipeline/term.html)

### Backtrader

- [Operating the platform](https://www.backtrader.com/docu/operating/)
- [Memory savings](https://www.backtrader.com/docu/memory-savings/memory-savings/)

### NautilusTrader

- [Data and Parquet catalog](https://nautilustrader.io/docs/latest/concepts/data/)
- [Backtest APIs and repeated runs](https://nautilustrader.io/docs/latest/concepts/backtesting/apis-and-runs/)
- [Backtest execution flow](https://nautilustrader.io/docs/latest/concepts/backtesting/execution-flow/)
- [Architecture](https://nautilustrader.io/docs/latest/concepts/architecture/)

### vectorbt

- [Feature overview](https://vectorbt.dev/getting-started/features/)
- [Portfolio API](https://vectorbt.dev/api/portfolio/base/)
- [IndicatorFactory and flexible broadcasting](https://vectorbt.dev/api/indicators/factory/)
