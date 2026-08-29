# Use an independent append-only CSI 300 Benchmark Snapshot

Strategy Comparison uses the ordinary CSI 300 Price Index Open level from the
first investable Entry Open through Terminal Valuation. The Benchmark Snapshot
is one current JSON file in an independent mounted Benchmark Store; it is not a
Canonical Dataset Family, Data Generation input, Product State record, or
immutable Result member.

The private Data Operator initially collects Tushare `index_daily` for
`399300.SZ` from 2010-01-04 through Market Coverage. Later Market Refreshes ask
only for Research Sessions after the Snapshot terminal session and append them.
Published historical Levels are fixed: the operator never re-requests,
corrects, or replaces an existing session. Each append atomically replaces the
complete file after validation and durable flush; no Snapshot history is kept.

Dataset Bootstrap and Market Refresh publish the Benchmark Snapshot before the
Market Head compare-and-swap. The Snapshot may therefore temporarily lead a
failed or concurrent Market publication, but a new Market Head may never lead
the Snapshot. Missing, duplicate, non-positive, non-finite, damaged, or
insufficient Benchmark data blocks that Market publication without a carry,
alternate index, remote runtime lookup, or other fallback.

Strategy execution, continuation, retry, Tracking Checkpoints, and immutable
Results contain only Strategy facts. Product read models align those facts with
the current Snapshot; comparison unavailability does not make Strategy
execution or Tracking unavailable.
