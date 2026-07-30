---
status: accepted
---

# Continue DailyTrack across historical corrections without replay

When a normal Dataset Release contains an accepted historical correction that
affects an active DailyTrack's Alpha, Universe, Label, Benchmark, execution, or
accounting dependency closure, the Track continues through an ordinary
Tracking Advance. The platform does not stop the Track, create a new Tracking
Generation, or perform a full correction replay.

The Advance starts from the current Tracking Head Checkpoint and appends a new
Checkpoint in the same Generation. Every previously published Alpha, matured
Label, order, holding, cash value, cost, NAV value, Benchmark observation, and
pending Strategy decision remains unchanged. A signal already committed by an
earlier close executes as committed even when the target Release now contains
corrected inputs that would have produced a different historical signal.

Results first published by the boundary Advance use its target Dataset Release.
This includes new-session rolling inputs and Alpha Values and Labels that first
reach maturity in that Advance. A new Factor Summary Snapshot uses the retained
immutable observation sequence plus the newly published observations; it does
not recalculate older observations from the corrected Release. Strategy and
Benchmark processing continue from the committed predecessor state.

The new Checkpoint records that it is a Tracking Correction Boundary and binds
the target Release whose correction change-set became effective. This makes the
intentional discontinuity visible instead of presenting it as investment
performance or a silently repaired history. The Head moves only after the
entire Advance passes its ordinary data, numeric, accounting, checksum, and
atomic-publication gates.

The Track remains reproducible, but its input identity is no longer one latest
Dataset Release. The Activation Checkpoint followed by the ordered predecessor
chain of successful Checkpoints and each Checkpoint's
`target_dataset_release_id` defines the exact Release sequence. An equivalence
verification must apply that same sequence at the same Advance boundaries. A
batch calculation that instead applies the Head's corrected Release from the
Tracking Origin describes the counterfactual result that would have occurred
if the correction had always been known; it is not required to equal the
accepted as-operated Track.

This decision accepts that an active Track after a correction may contain old
committed state followed by new calculations that use corrected historical
lookback. It favors inexpensive append-only daily continuity on the first
hosted node over automatic historical repair. Older Dataset Releases and
Checkpoints remain immutable and queryable, so the correction boundary and both
data versions remain auditable.

This decision supersedes ADR-0107 for historical data corrections. It does not
change ADR-0109's separate rule for a result-changing calculation-kernel
correction.
