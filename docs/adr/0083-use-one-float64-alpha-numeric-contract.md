---
status: accepted
---

# Use one float64 Alpha numeric contract

At the Alpha Expression evaluation boundary, V1 converts every valid Canonical
numeric input to IEEE 754 binary64 (`float64`). Every arithmetic operation and
built-in Alpha function consumes and produces `float64`. The runtime performs
no configured decimal rounding or quantization on intermediate or final Alpha
Values.

The scalar functions have these fixed meanings:

```text
log(x)  = natural logarithm ln(x)
sign(x) = -1 when x < 0
           0 when x = 0, including -0.0
           1 when x > 0
```

`ts_std(x,n)` is the population standard deviation over its complete valid
window, using `ddof=0`. A one-observation valid window therefore returns zero.
This Alpha rolling statistic is independent of the sample standard deviations
used later for report metrics.

Division by positive or negative zero, `log(x)` for `x <= 0`, and any operation
that yields NaN or positive or negative infinity produces a Missing Alpha
Value. Strict propagation then follows ADR-0030.

Canonical Dataset storage types remain governed by their Dataset Schemas. This
decision fixes the Alpha runtime boundary; it does not require market data to
be physically stored as binary floating point.

Both reference and columnar Research convert each finite Decimal-backed
Canonical input with the Numeric Execution Contract's correctly rounded
Decimal-to-binary64 operation. An Arrow decimal cast is not equivalent because
it can select the adjacent binary64 value; correctness at this boundary is more
important than a shorter conversion path.
