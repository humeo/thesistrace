---
status: accepted
---

# Create a new Tracking Generation for a historical correction

Normal DailyTrack Advances append from the previous Checkpoint. If a new
Dataset Release contains an accepted historical correction that changes any
dependency in the DailyTrack's Alpha, Universe, Label, Benchmark, execution, or
accounting closure, append-only continuation can no longer satisfy
Batch-Incremental Equivalence.

V1 then creates a new immutable Tracking Generation and fully replays from the
original Tracking Origin through the corrected target Dataset Release. The
Release's cumulative logical snapshot under ADR-0013 supplies the complete
Origin-to-target closure. Replay resolves market data and dependencies from
that corrected Release; it does not use the old seed Result Bundle or prior
Generation Checkpoint as calculation input.

The replay publishes the new Generation's root Checkpoint with
`predecessor = none`, its Tracking Origin, corrected
`basis_dataset_release_id`, and `supersedes_generation_id` plus the superseded
Head. Every later predecessor must belong to that same new Generation. The
full Advance identity remains
`(daily_track_id, generation_id, target_dataset_release_id)`.

V1 does not attempt a smart partial calculation repair. Unchanged immutable
Physical Data Objects and generation-and-release-neutral content payloads may
still be referenced by content hash rather than copied. Checkpoints, Label
Maturation events, Factor Summary Snapshots, and other provenance-bearing
artifacts are republished for the new Generation and record its
`generation_id`, corrected replay basis Release, and original effective session
or maturity coordinate.

The previous as-known Generation, its Checkpoints, and observations remain
queryable and unchanged. Only after the corrected replay succeeds does the
DailyTrack's Tracking Head atomically move to the new Generation. Until then,
the prior Head remains readable and the Track reports that it is behind or
blocked at the corrected release.

This rule does not add a historical-correction discovery scan. ADR-0091 still
uses incremental source ingestion, and ADR-0088 still waits for a normal
new-session Dataset Release before publishing an already discovered
correction.
