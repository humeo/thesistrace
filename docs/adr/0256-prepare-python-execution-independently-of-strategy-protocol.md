---
status: accepted
---

# Prepare Python execution independently of the strategy protocol

[ADR-0257](0257-freeze-numerical-python-libraries-and-transfer-history-arrays.md)
replaces the bytecode-loader implementation below with preinitialized numerical
libraries and binary history arrays, retaining the execution/strategy separation.

The shared simulator owns event ordering and the account. The Python Strategy
Adapter owns SDK entrypoints, decision validation, explicit state, and the
decision-scoped history capability. A prepared Python execution Module receives
opaque input, an explicit clock, and a bounded request callback; it does not
classify strategies or choose their invocation frequency.

Retain the pinned CPython/WASI sandbox and fresh guest per invocation. Prepare
trusted protocol bytecode and the standard-library import closure once with the
same interpreter that executes them. Load permitted library modules on demand
through an immutable bytecode capability backed by Python's importlib. This
capability accepts module names from the prepared catalog only, not paths, and
has independent request and byte bounds. Revoke the filesystem capability before
user code. No module mutations, globals, or ordinary attributes survive calls.
SDK source remains researcher-visible; this does not require changing Python
strategies into an Alpha expression or inferring their history requirements.

The native-CPython template/fork candidate is not adopted: replacing the
interpreter is unnecessary for these preparation and data-path improvements and
would require separate qualification of deterministic inputs and isolation.
This replaces the eager standard-library initialization described in ADR-0252
and ADR-0255, not their state, simulation, or resource contracts.

History loading aligns Arrow columns and converts numeric columns without
materializing one Python row dictionary per observation. Decimal columns pass
through exact decimal text before float conversion because Arrow's direct
Decimal-to-float cast can double-round. The strategy Adapter validates and
encodes each history response once; the execution Module transports those bytes.
The SDK wraps numeric history rows as immutable tuples without recursively
visiting every scalar again. Missing values, ordering, data visibility and
numeric input values retain their existing meaning.

The frozen execution identity includes the changed SDK/bootstrap and library
loader. New admissions use that identity. Historical inputs, results, and
checkpoints are not rewritten; a different frozen environment is still rejected
on execution. API and all Python-capable Worker pools must use the same revision.
Cut over after pending execution is drained, and explicitly resolve any affected
DailyTracks rather than silently running old state with a new environment.

Verification crosses the execution Interface and the Strategy Adapter: opaque
protocols, dynamic imports after filesystem revocation, fresh module state,
deterministic inputs, denied capabilities, deadlines, bounded transport, and
complete frozen-data backtest comparisons. Resource limits still cover the
entire supervised task, with the container memory limit as the final bound.
