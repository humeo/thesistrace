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
