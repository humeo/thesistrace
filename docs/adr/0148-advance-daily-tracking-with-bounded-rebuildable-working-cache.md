---
status: accepted
---

# Advance Daily Tracking with bounded rebuildable working cache

A normal DailyTrack Advance processes only the Research Sessions added after
its current Tracking Checkpoint. It never performs an Origin-to-target batch
replay merely because one new Dataset Release added one session. Each new
Final Alpha Cross-Section reads the expression's complete Canonical input
window, whose Effective Alpha Lookback is at most 252 sessions, but previously
completed Alpha sessions are not recalculated.

Each active DailyTrack may keep one latest-only, non-authoritative Working Cache
outside the immutable Result Bundle and Tracking Checkpoint object graph:

- the Pending Alpha Cache holds Final Alpha Cross-Sections only until their
  1-, 5-, and 20-session Labels have all matured, so it contains at most the
  approximately 21 most recent signal sessions; and
- the Rolling Factor Observation Cache holds only the daily aggregate
  IC, Rank IC, Five-Quantile, Top-Bottom, coverage, status, and reason values for
  the latest 504 signal sessions and three horizons, at most 1,512 rows.

The cache is created only when a successful ResearchRun explicitly seeds a
DailyTrack. Activation builds it once from the seed Dataset Release and pinned
research semantics; ordinary ResearchRuns do not precompute or retain a
possible future Tracking cache. This avoids charging every Run for state used
only by the limited set of enabled DailyTracks.

When a Label exit coordinate enters the target Dataset Release, the Advance
pairs that return with its cached Final Alpha Cross-Section, calculates the
daily aggregate Factor observation, and does not persist a stock-level Label.
After the 20-session Label matures, that signal session's stock-level Alpha
rows are evicted. Factor summary statistics are recalculated in canonical order
from the small rolling aggregate cache rather than maintained through a
differently ordered online recurrence. The cache is not a Factor curve,
user-visible result, or provenance record.

The authoritative Tracking Checkpoint contains the resulting Factor Summary
Snapshot, newly retained Strategy Daily and bounded aggregate deltas, and
Terminal Strategy State. Strategy advances from its prior terminal state
through only the new sessions. A catch-up Release processes its missing
sessions sequentially inside one Advance.

Every cache records the DailyTrack, Generation, basis Tracking Head,
Definition hash, calculation-kernel version, Numeric Execution Contract, and
target Dataset Release. A missing cache or any basis mismatch causes that
cache to be discarded and rebuilt once from immutable inputs; a historical
correction still creates and fully replays a new Generation under ADR-0107.
Cache loss can therefore cost computation but cannot change or destroy result
truth. Exact batch-versus-incremental replay remains an explicit correctness
test under ADR-0108, not work repeated by every daily Advance.

Each active DailyTrack owns this replaceable layout outside the immutable
Object Store:

```text
cache/daily_tracks/{daily_track_id}/
├── basis.json
├── pending_alpha/
│   └── signal_date=YYYY-MM-DD.parquet
└── factor_observations.parquet
```

Pending Alpha has one ZSTD Parquet partition per signal session, ordered by
`instrument_id`, so a normal Advance writes one new partition and evicts the
partition whose 20-session Label has matured instead of rewriting all pending
Alpha rows. The at-most-1,512-row Rolling Factor Observation file is replaced
as one ZSTD Parquet file. New payloads are written to temporary names and
atomically renamed; `basis.json`, including the expected payload identities,
is atomically replaced last. Any interrupted or inconsistent layout fails its
basis check and is rebuilt instead of being accepted as result input.

The Working Cache is bounded by these session and row limits and is not charged
to ADR-0147's per-ResearchRun one-MiB result budget. V1 does not yet assign the
cache a separate hard byte limit. This decision supersedes ADR-0106.
