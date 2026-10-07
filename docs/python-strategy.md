# Python strategy SDK

The live **Research Authoring Reference** is available in Connections → MCP →
Research preparation → Read the authoring reference. It reads the same contract
as `get_authoring_reference(topic="python_sdk")`: omit `symbol` for the index,
then select e.g. `symbol="Data.history"` for signatures, parameter constraints,
return values and examples. Topics `workflow`, `formula` and `examples` cover the
other authoring steps. `get_alpha_catalog(kind="fields", query="close")` finds
currently available fields; `kind="functions"` browses Formula functions without
paging through fields. Diagnose the complete configuration with
`diagnose_research_spec` before submitting. These reads do not create research.

The platform supplies data and the actual simulated account. Your class decides
what should change. The platform then applies trading rules, costs and fills at
the next research trading session's Open. A returned target is not a guaranteed
fill. Rule configuration remains the default; Python implements custom logic.

## Write one strategy class

```python
from quantgrove import Strategy

class Momentum(Strategy):
    def on_close(self, data, account):
        lookback = 10
        improvement = 0.01
        prices = data.close_prices(lookback)
        if len(prices.sessions) < lookback:
            return None
        scores = {
            stock: closes[-1] / closes[0] - 1
            for stock, closes in prices.items()
            if closes[0] is not None and closes[-1] is not None and closes[0] > 0
        }
        eligible = [stock for stock in data.candidates if stock in scores]
        if not eligible:
            return None
        best = max(eligible, key=lambda stock: (scores[stock], stock))
        held = [position["instrument_id"] for position in account.positions]
        held_score = max((scores.get(stock, -1) for stock in held), default=-1)
        if best not in held and (not held or scores[best] > held_score + improvement):
            return self.target_weights({best: 1.0})
        return None
```

`10` and `0.01` are ordinary strategy constants. Change them or calculate them
using ordinary Python. They are not required platform parameters. Ten observations
cover nine adjacent trading-session intervals. This example is a template, not
a recommendation or a platform rule.

Define exactly one locally defined subclass of the required base, with a
zero-argument constructor and `on_close(self, data, account)`. Helpers and ordinary
imports are allowed within the installed environment. Class loading, top-level
code and construction all execute in the isolated guest, including during Check
configuration. Checking verifies syntax, the class and callback signature; it
does not execute every branch or certify future data requests. Runtime failures
include the source digest, decision date and author source line when available.

## System input

### Data

| Access | Meaning |
| --- | --- |
| `data.session` | Current Close decision date, ISO string |
| `data.completed_sessions` | Decision number since the original research start |
| `data.candidates` | Current permitted candidate instrument IDs |
| `data.candidate_details` | Read-only rows with instrument ID, board and industry |
| `data.close_prices(days, instruments=None)` | Causally adjusted Close history |
| `data.history(field_id, days, instruments=None)` | Numeric research field history |

Pass `instruments` by keyword to either history method. With no instrument
argument the scope is current candidates plus actual holdings. An explicit list
must contain unique IDs within that scope. Field IDs come from Browse fields,
which inserts a `data.history("price.close.adjusted", 10)` call at the editor's
selection. No separate declaration or history-window form exists.

Reads are real guest-to-host requests. `days` may be a variable or expression.
Each read uses the Run's pinned data generation and host-owned decision date;
the program cannot supply another as-of date or dataset. Financial values retain
the field's disclosure-time visibility. Current and earlier published research
sessions are available, including history before the research start or execution
chunk. No future calendar or future universe members are supplied.

The returned `History` has a read-only NumPy `array`, with instruments on rows and
oldest-to-newest sessions on columns. `history.instruments` and `history.sessions`
name those axes. Explicit instrument requests retain their row order; the default
scope is sorted by instrument ID. Missing observations are `NaN` in the array.
Use `array.copy()` for writable calculations.

The keyed `values`, `history[stock]` and `history.items()` views expose tuples of
floats or `None`, with keys in canonical instrument-ID order. They use the same
observations as the array and only materialize tuples when accessed.
If the generation starts too recently, fewer than `days` sessions are returned;
the strategy decides whether to wait or use them. Reading does not shift the
research start or create additional decisions. Unknown/unavailable fields and
out-of-scope stocks raise a source-located error rather than receiving substitute
data. Empty stock lists return no instrument values.

For example, compute every instrument's return in one NumPy operation:

```python
import numpy as np

history = data.close_prices(61)
if len(history.sessions) == 61:
    prices = history.array
    valid = np.isfinite(prices[:, 0]) & np.isfinite(prices[:, -1]) & (prices[:, 0] > 0)
    scores = prices[valid, -1] / prices[valid, 0] - 1
    instruments = np.asarray(history.instruments)[valid]
```

The execution layer does not infer a strategy category or translate Python into
a formula. NumPy operates on the requested, bounded window. Decisions that use
the actual account or explicit state still run in Close order. Convert NumPy
values to finite JSON with `tolist()` or `item()` before saving them in `self.state`.

### Account

`account` is recursively read-only. It exposes `cash_cny`, `positions`,
`post_open_net_nav_cny`, `close_risk_nav_cny`, `fills` and `rejections`.
Positions are actual holdings, including their `instrument_id`, execution shares,
adjusted units and holding-cycle facts. Fills and rejections concern the current
session. Money and exact accounting quantities retain the platform's decimal
string representation; use `Decimal` for arithmetic. Mutating a local variable
or constructing a decision cannot alter these authoritative account facts.

## Strategy output

| Return | Meaning |
| --- | --- |
| `None` or bare `return` | No update; do not replay the last target |
| `self.target_weights({stock: 0.8})` | Complete new portfolio: 80% stock, 20% cash; omitted holdings exit |
| `self.target_weights({})` | Explicit liquidation target |
| `self.increase_to_weights(weights)` | Only buy toward target weights; do not sell other holdings |
| `self.reduce_exposure(0.5)` | Proportionally reduce actual holdings toward an exposure ceiling; never buy |
| `self.limit_positions({stock: 100})` | Cap remaining execution shares of the named actual holding; leave others alone |
| `self.limit_exposure(0.5)` | Apply a portfolio exposure cap without a new allocation |
| `self.with_limits(decision, maximum_shares=..., maximum_exposure=...)` | Intersect caps with a decision; existing tighter caps remain |

Helpers construct a decision. **Only the decision returned by `on_close` is
submitted.** Calling two helpers does not submit two orders. Portfolio weights
must be positive and total at most one; omit zero-weight entries. Local share
caps cannot increase a holding. Optional `reason="..."` labels the decision.
The host validates all outputs and visible IDs independently of the SDK and
supplies execution coordinates. Exact internal ratio strings are not an authoring
requirement. Board lots, tradability, costs and cash can prevent full execution.

## Optional cross-session memory

Use `self.state`, a bounded JSON object, when a strategy needs memory:

```python
self.state["decisions"] = self.state.get("decisions", 0) + 1
```

The class is recreated in every isolated invocation. State is restored after
construction and before `on_close`; other instance attributes, globals and
objects do not survive. Do not rely on `self.state` inside the constructor.
State is separate from the account, and need not be returned explicitly.
An exception, invalid target or resource failure commits neither new state nor
the new decision. Each Run, Batch item and Framework module has independent
state; DailyTrack resumes the same frozen program and accepted state.

## Framework Python modules

Each stage uses `on_close(data, account)` and its own base class:

| Stage | Import / inherit | Return helper |
| --- | --- | --- |
| Candidate selection | `UniverseSelection` | `self.select(instruments)` |
| Scoring | `Alpha` | `self.signals({stock: score}, valid_for_sessions=1)` |
| Portfolio construction | `PortfolioConstruction` | Portfolio helpers above |
| Risk management | `RiskManagement` | `self.limit_positions(caps)` or `self.replace(decision)` |

`data.framework` is a read-only view of the selected universe, active signals,
universe/signal change facts, expired/removed signals, this Close's proposal and
the retained prior proposal. The retained proposal is a reference; it is never
implicitly replayed. Downstream candidate and history scopes follow Universe
Selection; actual holdings stay visible.

Universe `None` retains still-available selected candidates (initially empty).
Alpha outputs replace the signal snapshot; signal lifetime is 1–252 sessions.
Alpha `None` keeps unexpired signals. Expiry or removal does not itself sell.
Portfolio `None` creates no new proposal. Risk runs even without a new proposal:
`None` leaves it alone, `replace(None)` cancels it, and local caps intersect it.
For a full risk replacement use e.g.
`return self.replace(self.target_weights({}))`. The host rejects a helper result
that does not belong to its stage. Only the composed decision reaches execution.

## Submit, inspect and reuse

Web, HTTP and MCP submit `program: {"source": "..."}` plus simulation conditions.
Framework slots use `{"kind": "python", "program": {"source": "..."}}`.
There are no `parameters` or `data_requirements` properties. The current contract
is `python-strategy/v4`; the old function ABI is not an execution fallback.

Dates, universe, initial capital, fees and slippage remain backtest conditions.
The Run freezes source, execution identity and data generation. Results expose
that source for inspection and copying to a new draft. Copying or editing never
changes an existing Run or DailyTrack. Batch items retain separate states and
accounts, even when they share prepared market data.

Trading details → **Python data reads** records successful reads from accepted
decisions: module, field, requested/returned sessions, stock count, actual date
range and response bytes. It follows the same retention and ownership rules as
other event evidence and is not continuation state. A failed invocation does not
publish partial read records. No static data-use summary is inferred from Python.

## Dynamic read limits

Each invocation allows at most 64 requests, 253 sessions per request, 262,144
requested stock/session cells per request, and 1,048,576 cumulatively. The request
message is at most 64 KiB; each encoded response is at most 4 MiB and cumulative
responses at most 16 MiB. Requests cannot overlap unread responses. The host
checks scope and cell budgets before loading data and encoded size before giving
it to the guest. Reads share the invocation's wall-time budget. The supervised
worker remains responsible for bounding host work; guest fuel alone does not
bound storage access. Capacity planning reserves guest, host read and event buffers.

## Frozen environment

The current environment is a preinitialized **CPython 3.14.0 + NumPy 2.5.0**
WASI component, executed by Wasmtime 49.0.0. It uses componentize-py's pinned
WASI interpreter fork, rather than the previous CPython 3.14.7 command archive.
The portable component, source hashes, toolchain revision and dependency hashes
are packaged in `research_kernel/python_runtime/manifest.json`. The explicit
[build recipe](../tooling/python-runtime/README.md) records its source inputs,
patches and licenses. Execution verifies the packaged component; it never
fetches packages or inherits the host Python environment.

The runtime identity includes these versions, the component archive, actual
bootstrap and module-source hashes (including the SDK and history codec),
available modules, limits and deterministic-input policies. New admissions use
`python-strategy/v4`. Historical inputs and results remain unchanged; executing
an old frozen environment still fails explicitly. API and all Python-capable
Worker pools must use the same revision. Drain pending work and resolve affected
DailyTracks before a cutover.

Programs can import `numpy`, including its prepared `fft`, `linalg`, `ma`,
`polynomial`, `random`, `rec` and `strings` modules, and the supported standard
library: `bisect`, `calendar`, `collections`, `copy`, `dataclasses`, `datetime`,
`decimal`, `enum`, `fractions`, `functools`, `heapq`, `itertools`, `json`, `math`,
`operator`, `random`, `re`, `statistics`, `string`, `time` and `typing`, with their
prepared dependencies. Pandas and package installation are unavailable. NumPy
runs compiled array kernels inside WASI; this build has no external BLAS or
host CPU-specific dispatch. Batch arithmetic does not imply native BLAS speed.

Only trusted libraries are initialized in the component image. Every invocation
gets a fresh Store and component instance before receiving strategy source,
input, data or explicit state. Wasmtime shares compiled code and copy-on-write
initial memory; Python globals, module mutations and arrays never survive calls.
The executor receives opaque input and bounded host capabilities, without knowing
whether the caller is a Direct Strategy or any Framework stage.

The host grants no filesystem, network, subprocess or native-library authority.
The SDK's history callback returns only authorized observations up to this Close,
as a bounded, non-pickled float64 NPY matrix plus explicit axes. The guest exposes
an immutable bytes-backed ndarray and lazily creates keyed tuples for code using
`history[instrument]`. No Python object graph is serialized cell by cell on the
array path. Arrays expose missing values as NaN; keyed tuples retain None.
The only environment variables are fixed `PYTHONHOME=/runtime`,
`PYTHONHASHSEED=0` and `TZ=UTC`.

Wall-clock APIs, including NumPy's `datetime64("now")`, return 15:00 UTC+08:00 on
the decision session; monotonic and CPU clocks return zero. Random bytes,
including `SystemRandom` and unseeded NumPy generators, derive from the canonical
invocation. NumPy's legacy global RNG receives a separate domain-separated seed;
it does not consume the standard-library RNG stream. Explicit NumPy seeds retain
their usual meaning. Identical source, context and state receive identical random
input. Sleeping and blocking timer subscriptions are unavailable. The initialized
stdlib `random` is reseeded once before researcher source, preserving the prior
entropy sequence even when user code calls `os.urandom` first.

## Invocation limits

| Resource | Limit |
| --- | --- |
| Source / diagnostics | 65,536 UTF-8 bytes each |
| Complete input | 4 MiB |
| Complete output, including raw stdout and stderr | 1 MiB |
| Explicit state | 256 KiB |
| Guest linear memory | 128 MiB |
| Wasmtime fuel | 16,000,000,000 units |
| Trusted guest startup | 10 seconds |
| User program wall time | 3 seconds |
| JSON nesting | 32 levels |

Fuel bounds CPU work across the complete invocation. The trusted bootstrap
has its own bounded startup time for setting up the prepared environment. After
it prepares the SDK and immutable input, the user-program deadline starts;
source compilation, top-level code, the callback and serialization share that
3-second budget. Repeating the bootstrap readiness signal cannot restart it. Both budgets are
frozen in the execution identity, and wall deadlines also apply on overloaded
hosts. A deadline failure is an explicit failed invocation, not a different
successful result. The next invocation starts with a new guest and unchanged
platform authority. JSON permits finite numbers, strings, booleans, null, arrays
and string-keyed objects. Integers must be within ±(2^53−1); strings must be valid
UTF-8. Duplicate output keys and implicit or unserializable state are rejected.

MCP transport accepts requests up to 64 MiB, including JSON escaping for a
20-item Framework Batch with four Python programs per item, and responses up
to 16 MiB for complete targets and explicit state. HTTP request bodies have a
single 60-second read deadline independent of transport chunk count; oversized
bodies return 413 and incomplete bodies that exceed the deadline return 408.
`get_research_context` includes the `quantgrove` SDK module and complete Direct
and Framework source templates in its authoring constraints. Target evidence records
have a 2 MiB limit; their pages reserve that capacity plus the ordinary
32 KiB page budget. Framework event records have a 4 MiB limit; other event
records retain their 24 KiB limit. Worker event frames carry at most 512
records or 8 MiB of record bytes, within the existing 64 MiB acknowledged
segment limit. DailyTrack origin pages reserve the full current decision
state (3 MiB for Framework modules or 256 KiB for Direct) and a 2 MiB pending
target in addition to the ordinary 32 KiB page budget. These transport bounds
do not increase the program's source, state or execution limits.

Verification selection and commands are maintained only in
[AGENTS.md](../AGENTS.md#testing).

### Framework decision evidence

`strategy_framework` is a Trading Event section on Run and DailyTrack, with the
same ownership, retention and cursor rules as the execution sections. One record
per completed Close contains the four frozen module identities, current Universe
selection and update reason, the Alpha module's observed output, the new portfolio
proposal or `null`, and the explicit Risk Adjustment or `null`. Builtin Alpha
records the formula values consumed by the portfolio; Python Alpha records active
Strategy Signals with their creation Session and lifetime, new-output status,
expired instruments and instruments removed by Universe selection. An expired
signal is evidence of lifecycle processing, not an instruction to sell.

A `replace` Risk Adjustment with a null target is explicit cancellation; a null
Risk Adjustment leaves the current proposal alone. Position limits are recorded
before intersection with the proposal. `target_id` links the final Target Decision
when one exists, and is null for NoUpdate or cancellation. The final target and
actual orders/fills remain separate event sections. Direct emits no Framework
records. The result UI shows these stages separately and can follow the target
to actual execution.

Records are complete, typed and limited to 4 MiB each; worker frames and business
pages preserve whole records. They are never added to authoritative continuation
state and are not required to advance after Trading Event retention expires.
