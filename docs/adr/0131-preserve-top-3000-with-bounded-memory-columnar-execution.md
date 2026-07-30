---
status: accepted
---

# Preserve Top 3000 with bounded-memory columnar execution

Hosted Platform V2 preserves the Top 300, Top 1000, Top 2000, and Top 3000 Liquidity Universe contract without truncation or sampling. Top 3000 is the representative maximum Compute workload, so launch requires bounded-memory columnar execution and production Parquet paths that preserve the existing research semantics within the accepted resource envelope.
