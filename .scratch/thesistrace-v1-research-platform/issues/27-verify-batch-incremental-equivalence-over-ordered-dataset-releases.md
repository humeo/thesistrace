# 27 — Verify Batch-Incremental Equivalence over ordered Dataset Releases

**What to build:** Let the operator explicitly verify a DailyTrack by replaying
from its Tracking Origin through the exact ordered Dataset Release sequence
bound by its Checkpoint chain and comparing that reference execution with the
incremental path under the same pinned calculation and numeric contracts.

**Blocked by:** 26 — Continue DailyTrack through a Historical Correction
Boundary.

**Status:** resolved

- [x] Verification follows the Activation and Checkpoint Release sequence across same-Generation correction boundaries rather than treating the final cumulative Release as every historical input.
- [x] Reference and incremental execution use the same public calculation seam and compare Missing reasons, Alpha, Labels, Factor results, transient order and fill semantics, Strategy observations, Terminal Strategy State, and summaries.
- [x] Integers, Decimals, and binary64 values compare through canonical encodings with no tolerance; a mismatch returns a stable first divergent coordinate and `EQUIVALENCE_MISMATCH`.
- [x] Success and failure leave Tracking Head, immutable objects, and Working Cache unchanged and persist no Alpha, stock-level Label, daily Factor, order, or fill intermediates.
- [x] Ordinary Advances never run the full oracle, and acceptance covers both a same-Generation historical correction and a result-changing kernel Generation.
