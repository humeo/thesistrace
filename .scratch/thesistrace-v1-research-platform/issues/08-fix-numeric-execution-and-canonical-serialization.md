# 08 — Fix numeric execution and canonical serialization

**What to build:** Provide one versioned numeric boundary for exact integers,
Strategy Decimal accounting, binary64 research values, normalized serialization,
and content checksums.

**Blocked by:** 01 — Start the empty Web Workspace.

**Status:** resolved

- [x] Accounting Decimal uses 34 digits, half-even rounding, the fixed exponent range, and no cent quantization.
- [x] Division-by-zero, invalid, overflow, NaN, and infinity never enter authoritative artifacts.
- [x] Integer and Decimal encodings are minimal and canonical, including explicit normalized Decimal exponents.
- [x] Binary64 checksums use big-endian bytes with negative zero normalized to positive zero.
- [x] Decimal-to-binary64 conversion occurs only at declared boundaries with ties-to-even rounding.
- [x] Deterministic last-digit accounting residuals are preserved, reproducible, and never reported as Transaction Costs.
- [x] Numeric-contract tests use cross-process golden checksums rather than UI formatting.

## Comments

- Added the versioned 34-digit accounting context, canonical integer/Decimal
  encodings, finite-value guards, declared Decimal-to-binary64 conversion, and
  normalized big-endian binary64 checksums.
- Verified canonical examples and cross-process golden checksum stability at
  the public calculation seam.
