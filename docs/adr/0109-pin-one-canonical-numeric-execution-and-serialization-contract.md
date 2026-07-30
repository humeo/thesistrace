---
status: accepted
---

# Pin one canonical numeric execution and serialization contract

V1 names and versions one Numeric Execution Contract rather than relying on a
language, database, or library default. A frozen Research Definition and its
DailyTrack pin that contract identity. Every numeric artifact declares one of
the contract's exact integer, accounting decimal, or IEEE 754 binary64
representations. The system records the current supported identity when it
freezes a Definition; it is not another user-authored Research Definition
option.

Execution Share Quantities and other integral counts use exact integers.
Strategy decision and accounting arithmetic—including Adjusted Holding Units,
notional, target value, affordability, Transaction Costs, cash, position value,
and NAV—uses the `accounting_decimal_v1` context:

```text
precision: 34 significant decimal digits
rounding: ROUND_HALF_EVEN
Emin: -6143
Emax: 6144
clamp: 1
```

Every primitive decimal operation is evaluated in that context. This is a
decimal128-compatible execution convention, not a claim of infinite decimal
precision. It does not quantize an order, fee, cash balance, or NAV to CNY 0.01;
ADR-0094's no-per-order-cent-rounding rule remains unchanged. A decimal
operation that produces NaN or infinity, or raises division-by-zero, invalid,
or overflow, fails the calculation rather than entering a result.

Finite precision means a divided value need not multiply back to its
real-number starting value exactly. ADR-0070 therefore accepts the resulting
deterministic last-digit execution-rounding residual instead of introducing a
balancing account. Batch and incremental paths must produce the same residual;
it is not Transaction Cost and never changes Raw Notional, order eligibility,
or share quantity.

ADR-0083 continues to govern Alpha Expression binary64 arithmetic. Other
binary64 artifacts use the representation and deterministic operation order
declared by their calculation-kernel semantic version. Conversion from a
Canonical decimal value to binary64 uses IEEE 754 `roundTiesToEven` exactly once
at the declared boundary; implementations may not convert back and forth
implicitly.

Canonical equality and checksums use these encodings:

- an integer is its minimal signed base-10 form, with zero encoded as `0`;
- a finite decimal is its minimal signed, no-leading-zero,
  trailing-zero-free coefficient multiplied by ten to its normalized
  coefficient exponent, encoded as `[-]coefficient` followed by `e` and an
  exponent that always includes `+` or `-`; every decimal zero is encoded as
  `0`; and
- a finite binary64 value is its big-endian IEEE 754 eight-byte encoding after
  converting negative zero to positive zero.

For example, decimal `123.4500` is exactly
`12345 × 10^-2` and is encoded as `12345e-2`; decimal `1` is encoded as
`1e+0`. UI decimal formatting, scientific notation choices, localized
separators, and report rounding never enter equality or checksums.

Each Tracking Generation pins one calculation-kernel semantic version in
addition to the DailyTrack's numeric contract. Ordinary deployment build IDs
may vary by Checkpoint only when they declare compatibility with both pinned
versions. An accepted historical data correction does not change the kernel or
Generation and follows ADR-0144. A result-changing runtime correction is a
different boundary: it requires a new Generation and full execution from the
Tracking Origin with a predecessor-free root and superseded-Generation
provenance. Its basis is the current Tracking Head Checkpoint's target Dataset
Release; only a successful complete execution atomically moves Head, after
which later Release Advances may continue. A changed research or Numeric
Execution Contract requires a new successful ResearchRun and DailyTrack.
