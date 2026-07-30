---
status: accepted
---

# Propagate missing and invalid Alpha inputs strictly

A V1 rolling Alpha function produces a value only when every one of the `n`
market-session positions in its window contains a valid input. It does not use
a partial window, skip a missing session, or search farther back. Other Alpha
operations propagate a missing operand.

Division by zero, `log(x)` for `x <= 0`, and any operation that produces NaN or
infinity yield a missing Alpha Value. The formula engine does not replace
missing or invalid results with zero, carry values forward, or otherwise
impute them. ADR-0083 defines these checks on the `float64` result of each
operation. A complete one-observation `ts_std` window validly returns zero
rather than missing.

An instrument with a missing Alpha Expression output is excluded before the
Final Alpha Cross-Section for that session, and the resulting coverage loss is
reported. ADR-0077 defines the remaining sample pipeline. ADR-0046 defines
Strategy behavior for an existing position when a scheduled new Alpha Value is
missing.
