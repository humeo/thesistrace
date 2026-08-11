---
status: superseded by ADR-0155
---

# Use incremental daily ingestion without a historical-correction scan

The initial V1 Dataset Bootstrap fetches the configured Research Input History
and every required dependency.
After bootstrap, each normal post-close Dataset Publication fetches the newly
completed Research Session and the other source slices required for that
candidate release. It does not re-fetch the complete three-year history merely
to search for changed Tushare rows.

Causal cumulative adjustment derives adjusted OHLC from each row's raw price
and same-session factor. Appending a new factor therefore computes only the new
row and never rescales retained history. Recomputing an overlap row is needed
only when one of that row's accepted source facts changes.

V1 therefore does not promise to discover historical Tushare corrections
automatically. If an overlapping fetch, recovery, or future repair workflow
does discover a valid historical insert, update, or deletion, it may become an
accepted pending correction. ADR-0088 then incorporates it into the next
normal Dataset Release rather than publishing a correction-only release.

This decision limits automatic correction freshness, but keeps the ordinary
daily publication path incremental and avoids a full historical source scan
after every market close. Older Dataset Releases remain immutable regardless
of whether a later correction is discovered.
