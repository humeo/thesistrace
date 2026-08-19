---
status: accepted
---

# Share one columnar coordinate index and correct Decimal conversion

One bounded ResearchRun Execution Chunk builds one ordered integer coordinate
index for each Canonical table slice. Alpha fields, Factor adjusted Opens,
Strategy execution prices, trading states, price limits, and Effective Universe
eligibility reuse those indexes rather than independently expanding the same
Arrow session and instrument columns into Python coordinate tuples.

Decimal-backed numeric Alpha and Factor inputs use the Numeric Execution
Contract's correctly rounded `Decimal` to IEEE 754 binary64 conversion. The
columnar path must not use Arrow's decimal-to-float cast because that cast can
select the adjacent binary64 value. Strategy retains the same Decimal matrix
used by its accounting and Benchmark rules; the corresponding binary64 matrix
is derived from those same Decimal values once per Chunk.

Strategy candidate selection computes only the frozen holdings count with a
stable Top-K ordered by descending Alpha and ascending instrument identity.
When the explicit audit ledger is requested, the same module additionally
materializes the complete ranking. Both forms preserve the exact selected
instruments and all downstream order, fill, cost, cash, holdings, NAV, and
Benchmark semantics.

Alpha field matrices use the ordered union of the selected Universe members in
the bounded calculation slice rather than every instrument in the market
reference table. Factor adjusted-Open matrices use the instruments that have
Alpha observations, and the Strategy Benchmark matrices use the ordered union
of their selected Universe members. These are coordinate projections only:
the frozen per-session Universe, Alpha order, labels, Benchmark composition,
held positions, accounting, and published scientific values do not change.

These changes deepen the existing Columnar Research module; they do not add a
second calculation engine, alternate numeric route, adaptive Chunk plan, or
parallel execution slot. Result-changing Decimal correction hard-cuts the
single active Kernel identity to `kernel-v4` under ADR-0211. Development Product
State accepted under an earlier Kernel identity is not resumed or reinterpreted.
