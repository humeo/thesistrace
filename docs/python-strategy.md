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
| Wall time | 3 seconds |
| JSON nesting | 32 levels |

Fuel bounds CPU work; the wall deadline also bounds execution on an overloaded
host. A deadline failure is an explicit failed invocation, not a different
successful result. The next invocation starts with a new guest and unchanged
platform authority. JSON permits finite numbers, strings, booleans, null, arrays
and string-keyed objects. Integers must be within ±(2^53−1); strings must be valid
UTF-8. Duplicate output keys and implicit or unserializable state are rejected.

Verification selection and commands are maintained only in
[AGENTS.md](../AGENTS.md#testing).
