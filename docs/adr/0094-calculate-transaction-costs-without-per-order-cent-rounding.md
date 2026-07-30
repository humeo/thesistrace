---
status: accepted
---

# Calculate Transaction Costs without per-order cent rounding

V1 evaluates the Transaction Cost formulas in ADR-0050 with decimal arithmetic
and does not round an individual commission, transfer fee, stamp duty, or Child
Order total to CNY 0.01. The unrounded calculated amounts feed affordability,
Net Cash, Net NAV, and every downstream metric.

ADR-0109 fixes the decimal execution precision, rounding mode, and canonical
encoding; this ADR prohibits currency-cent quantization rather than claiming
infinite decimal precision.

Reports may format CNY amounts to two decimal places for display, but that
presentation never changes the stored accounting values or the result of later
calculations. This is a deterministic research-model convention rather than a
claim about one broker's invoice-rounding behavior.
