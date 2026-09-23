# Python program execution contract

The Strategy runtime calls `decide(context, state, parameters)` in a fresh
CPython guest for every decision. The callback returns exactly
`{"output": ..., "state": {...}}`. The strategy adapter validates `output`
before the shared account can execute it. Only the returned JSON state survives
the invocation; globals, imported modules, closures and Python objects do not.

`context` and `parameters` are recursively read-only. `state` is a mutable copy
of the last accepted explicit state. Programs cannot change the platform's
account or order ledger. Invalid output, an exception or a resource limit fails
the invocation; it never substitutes an empty state or another strategy.
Diagnostics include the source SHA-256, decision session and source line when
available. Source, parameters, state and diagnostics are private research content.

## Direct Strategy authoring

Select **Strategy Backtest → Direct · Python** in Research. The active definition
contains source, a JSON parameter object, declared canonical field IDs and a
history length of 1–253 trading sessions (including the decision session), with
at most 32 unique fields. Switching mode removes the inactive definition.
Check configuration and submission use the same admission contract. HTTP and
MCP accept `strategy_mode: "direct"` with `program` and `initial_cash_cny`; Alpha,
neutralization, Top-N and selection-interval fields are not accepted in Direct.

The accepted Run freezes the source digest, parameters, data declaration and
runtime identity. Its result exposes that frozen definition for inspection and
reuse as a new Draft. DailyTrack inherits it; editing a Draft never changes a
Run or Track. A Strategy Sweep contains only Direct items or only Framework
items. Direct items have independent programs, state, accounts and results;
there is no shared Python or Alpha calculation.

At each research session's Close, the callback receives:

- `session` and `completed_sessions`: the current date and the number of
  decisions since the original research start. No future calendar is supplied.
- `history`: declared `fields` as row-by-column numeric arrays, with row order
  in `instruments` and column order in `sessions`. The view contains current
  candidates and actual holdings, ends at the current Close, and includes
  declared warmup. Financial fields retain the Dataset's disclosure visibility
  rule. Missing values are `None`.
- `candidates`: current instrument IDs and board metadata; `industry` is the
  current prepared industry value or `None` when unavailable. Future listing
  termination and future universe members are not exposed.
- `account`: authoritative cash, post-Open net NAV and actual positions;
  `fills` and `rejections`: this session's completed execution evidence.

Return `{"output": None, "state": state}` for NoUpdate. It does not rebalance
drift, spend leftover cash or replay a previous target. Otherwise `output` has
exactly `reason`, `allocation` and `position_limits`. Allocation specifies
`mode` (`rebalance`, `reduce` or `increase`), `instrument_ids`,
`relative_weights` (exact ratio strings) and `exposure` in [0, 1]. Use a null
allocation for local position reductions; `position_limits` maps held IDs to
maximum remaining integer shares. At least one action must be present. IDs must
be visible candidates or actual holdings; local limits cannot increase holdings.
The platform supplies the decision date, next-Open execution coordinate and
contract identity, then uses the same execution/account as Framework.

Weights use reduced positive integer ratios such as `"1/2"` or `"1"`, with
at most 128 decimal digits in each numerator and denominator. Their combined
denominator is limited to 4,096 bits. Decimal/exponent strings are rejected
before numeric parsing, so output validation also has bounded host cost.

The initial UI example replaces a holding only when a candidate's five-session
momentum improves enough. This minimal example instead enters the first visible
candidate once and keeps its actual holdings thereafter:

```python
def decide(context, state, parameters):
    output = None
    if not context["account"]["positions"] and context["candidates"]:
        selected = context["candidates"][0]["instrument_id"]
        output = {
            "reason": "enter_visible_candidate",
            "allocation": {
                "mode": "rebalance", "instrument_ids": [selected],
                "relative_weights": {selected: "1"}, "exposure": 1.0,
            },
            "position_limits": {},
        }
    state["decisions"] = state.get("decisions", 0) + 1
    return {"output": output, "state": state}
```

Declarations whose history cannot fit even its minimum JSON encoding are
rejected before host materialization. Exact input size is checked before guest
execution. A size failure includes the program and decision date and does not
publish partial state or orders. Declare only the fields/history the program
uses; narrower declarations reduce input and calculation cost.

## Framework modules

HTTP and MCP accept `strategy_mode: "framework"` and a `modules` object with
exactly these four slots, evaluated in this fixed order at each Close:

| Slot | Built-in identity | Python output |
| --- | --- | --- |
| `universe_selection` | `dataset_universe/v1` | `None`, or `{reason, instrument_ids}` |
| `alpha` | `alpha_formula/v1` | `None`, or `{reason, signals}` |
| `portfolio_construction` | `periodic_top_n/v1` | `None`, or the Direct target shape |
| `risk_management` | `no_risk/v1` | `None`, or an explicit Risk Adjustment |

Replace a slot's built-in string with `{"kind": "python", "program": {...}}`.
Each program has the same source, parameters and data declaration contract as
Direct, its own explicit state, and its own isolated invocation. All four
slots are frozen with the Run. Omitting `modules` selects all four built-ins.

The Research workbench exposes the four stages in the same order. Each stage
can use its built-in implementation or a Python module with independent source,
parameters and data declarations. Switching a stage clears its inactive settings.
The initial Python examples select available candidates, publish momentum signals,
replace a holding when another signal exceeds the improvement threshold, and exit
explicitly listed holdings. They are editable examples, not additional platform
rules. Run details retain every frozen module; Create draft copies those definitions
without changing an existing Run or DailyTrack.

Only built-in Alpha accepts `formula` and `neutralization`. Only built-in
Portfolio accepts `holdings_count`, `selection_every_sessions`,
`exposure_expression`, `weighting` and `volatility_window`. Inactive settings
must be omitted. The shared data preparation uses the union of declarations;
each program still sees only its own declared fields and history.

Every module receives the ordinary daily context plus `context.framework`:
`universe`, active `signals`, `universe_changed`, `signals_updated`,
`expired_signals`, `removed_signals`, the current `proposal`, and the
`retained_proposal` from the last Portfolio update. The last value is a
reference, never an instruction to replay old weights. Downstream candidate
lists are restricted by Universe Selection; actual holdings remain visible.

Universe output replaces the selected list with up to 3,000 unique current
Dataset candidates. `None` retains previously selected candidates that remain
available; it starts empty. Built-in Alpha retains the Research Universe's
original rank and neutralization population, then Universe Selection filters
strategy candidates. A Python Alpha may compute on its selected candidates.

Each Python signal contains `instrument_id`, a finite numeric `value`, and
`valid_for_sessions` from 1 to 252. Output replaces the active snapshot with at
most one signal per selected instrument. The host stamps `created_session`
and `created_session_number`; a lifetime of one expires before the next Close
decision. `None` retains unexpired signals. Expiry and Universe removal are
inputs to Portfolio Construction; neither creates a sale by itself. Built-in
Portfolio keeps its every-N-session selection policy even when signals change
daily. Python Portfolio can instead react to opportunity changes.

Risk runs every Close, including when Portfolio returns NoUpdate. Its output
must state the intended composition:

- `{"mode": "limit_positions", "reason": "...", "position_limits": {...}}`
  caps actual remaining shares. These caps intersect any Portfolio share caps;
  they cannot increase a holding. With no new Portfolio proposal, reducing A
  leaves B/C shares and the released cash unchanged.
- `{"mode": "replace", "reason": "...", "target": ...}` explicitly replaces
  the entire proposal with a Direct target shape; a null target cancels it.
- `None` leaves this Close's new proposal unchanged. It never restores the
  retained proposal or buys back a previous reduction.

The composed target alone reaches the shared execution account. A Framework
Strategy Sweep requires either built-in Alpha for every item (one shared
formula and neutralization) or Python Alpha for every item (no shared formula).
Python modules, active signals and accounts remain independent between items.

## Frozen environment

The runtime uses CPython 3.14.7 compiled for WASI, executed by Wasmtime 49.0.0.
The archive is the [CPython WASI build](https://github.com/brettcannon/cpython-wasi-build/releases/tag/v3.14.7)
`python-3.14.7-wasi_sdk-24.zip`, 14,291,017 bytes, SHA-256
`2e064d3fb8172471d39d741348efa722349c40b96301f69968dff714999c584b`.
Installation is an explicit dependency setup operation; execution neither
downloads packages nor inherits the host Python environment.

The runtime identity records these versions, the archive and trusted bootstrap
hashes, available modules, limits and deterministic-input policies. Changing
that identity changes the accepted execution environment.

Programs can import `bisect`, `calendar`, `collections`, `copy`, `dataclasses`,
`datetime`, `decimal`, `enum`, `fractions`, `functools`, `heapq`, `itertools`,
`json`, `math`, `operator`, `random`, `re`, `statistics`, `string`, `time` and
`typing`, with their already loaded dependencies. NumPy, pandas and package
installation are unavailable in the guest.

The host does not grant filesystem, network, subprocess or native-library
capabilities. The trusted bootstrap loads the fixed standard library, then
closes its sole directory capability and input descriptor before any user
source executes. Imports are not the security boundary: the WASI guest has no
host file, credential, dataset or socket authority even if a program reaches
Python's lower-level modules. The only environment variables are fixed
`PYTHONHOME=/runtime`, `PYTHONHASHSEED=0` and `TZ=UTC`.

Wall-clock APIs return 15:00 UTC+08:00 on the decision session; monotonic and CPU
clocks return zero. Random bytes, including `SystemRandom`, derive from the
canonical invocation. Identical source, context, state and parameters therefore
receive identical random input. Sleeping and blocking are unavailable.

## Invocation limits

| Resource | Limit |
| --- | --- |
| Source / parameters / diagnostics | 65,536 UTF-8 bytes each |
| Complete input | 4 MiB |
| Complete output, including raw stdout and stderr | 1 MiB |
| Explicit state | 256 KiB |
| Guest linear memory | 128 MiB |
| Wasmtime fuel | 16,000,000,000 units |
| Trusted guest startup | 10 seconds |
| User program wall time | 3 seconds |
| JSON nesting | 32 levels |

Fuel bounds CPU work across the complete invocation. The trusted bootstrap
has its own bounded startup time for loading the pinned standard library. After
it revokes the library and input descriptors, the user-program deadline starts;
source compilation, top-level code, the callback and serialization share that
3-second budget. Repeating the bootstrap readiness signal cannot restart it. Both budgets are
frozen in the execution identity, and wall deadlines also apply on overloaded
hosts. A deadline failure is an explicit failed invocation, not a different
successful result. The next invocation starts with a new guest and unchanged
platform authority. JSON permits finite numbers, strings, booleans, null, arrays
and string-keyed objects. Integers must be within ±(2^53−1); strings must be valid
UTF-8. Duplicate output keys and implicit or unserializable state are rejected.

MCP transport accepts requests up to 16 MiB, including JSON escaping for a
20-program Batch, and responses up to 8 MiB for complete targets and explicit
state. Target evidence records have a 2 MiB limit; their pages reserve that
capacity plus the ordinary 32 KiB page budget. Other event records retain their
24 KiB limit. Worker event frames carry at most 512 records or 8 MiB of record
bytes, within the existing 64 MiB acknowledged segment limit.
Direct DailyTrack origin pages reserve the bounded 1 MiB program output
in addition to the ordinary 32 KiB record-page budget. These transport bounds
do not increase the program's source, parameter, state or execution limits.

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
