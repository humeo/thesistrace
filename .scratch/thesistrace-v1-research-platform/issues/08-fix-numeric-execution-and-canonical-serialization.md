# 08 — Fix numeric execution and canonical serialization

**What to build:** Provide one versioned numeric boundary for exact integers,
Strategy Decimal accounting, binary64 research values, normalized serialization,
and content checksums.

**Blocked by:** 01 — Start the empty Web Workspace.

**Status:** ready-for-agent

- [ ] Accounting Decimal uses 34 digits, half-even rounding, the fixed exponent range, and no cent quantization.
- [ ] Division-by-zero, invalid, overflow, NaN, and infinity never enter authoritative artifacts.
- [ ] Integer and Decimal encodings are minimal and canonical, including explicit normalized Decimal exponents.
- [ ] Binary64 checksums use big-endian bytes with negative zero normalized to positive zero.
- [ ] Decimal-to-binary64 conversion occurs only at declared boundaries with ties-to-even rounding.
- [ ] Deterministic last-digit accounting residuals are preserved, reproducible, and never reported as Transaction Costs.
- [ ] Numeric-contract tests use cross-process golden checksums rather than UI formatting.
