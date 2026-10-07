---
status: accepted
---

# Freeze numerical Python libraries and transfer history arrays

Keep ADR-0256's separation: the simulator owns event ordering and the account,
the Strategy Adapter owns SDK callbacks and observations, and the Python execution
Module accepts an opaque payload, an explicit clock and a bounded read callback.
The executor does not classify programs by Alpha or translate Python into formulas.

Replace repeated interpreter/library initialization with a pinned, preinitialized
CPython + NumPy WASI component built with componentize-py. Each invocation receives
a new Store and component instance. Wasmtime shares compiled code and initialized
pages using its supported cache and copy-on-write mechanism; mutable Python
modules, globals, arrays and ordinary attributes remain invocation-local. Only
explicit, validated JSON state crosses decision sessions. Account-dependent
callbacks retain sequential Close semantics and next-Open execution.

NumPy evaluates whole history matrices across instruments and observations inside
the guest. Data returns a scoped float64 matrix with explicit instrument/session
axes. The bounded wire is one metadata line and a standard NPY array without
pickle. The SDK exposes a bytes-backed read-only ndarray and lazily creates the
existing keyed tuple view. Missing values are NaN in the array and None in tuples;
keyed iteration retains canonical instrument ordering, while the array exposes
its request-order axes. Decimal-to-float rounding, completed-session visibility,
read budgets and simulation accounting retain their prior contracts.

The component includes trusted libraries only, never user source or data. No
filesystem, credentials, sockets or host native-library capabilities are granted.
All wall-clock and entropy imports receive fixed simulation inputs. Standard
library random preserves its prior input sequence; NumPy's legacy global RNG gets
a separate payload-derived seed. Sleeping and timer subscriptions are denied.
Existing invocation and supervised worker limits remain enforced; a 128-session
chunk cap is not a substitute for the whole worker's hard memory ceiling.

The runtime is a new explicit environment (`python-strategy/v4`): componentize-py's
CPython 3.14.0 WASI fork and NumPy 2.5.0, with Wasmtime 49.0.0. This replaces the
3.14.7 command archive and bytecode-loader implementation in ADR-0256. It does not
silently upgrade historical inputs, results or active DailyTracks. Drain pending
work, resolve affected tracks, and activate the same revision in API and every
Python-capable Worker pool. Old frozen environments remain rejected.

A native pre-fork CPython candidate could reuse libraries but does not preserve
fixed clocks and entropy for native extensions with the existing isolation
contract. Pyodide's private memory-snapshot interface is not adopted. The pinned
WASI component retains authority and determinism at the runtime seam. It adds a
source build artifact and has no external BLAS or host SIMD dispatch; performance
claims therefore require complete real-data replays, not just NumPy microbenchmarks.

Build inputs, toolchain digest, local patches, packaged source and output checksums
are recorded together, with third-party licenses. Execution verifies the portable
component and never downloads dependencies. Rebuilds and resource-boundary changes
must be qualified through the public executor and strategy interfaces, plus the
installed image and supervised backtest. Follow the verification selection in
[AGENTS.md](../../AGENTS.md#testing).
