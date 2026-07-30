---
status: accepted
---

# Publish one immutable Tracking Checkpoint per Advance

Each
`(daily_track_id, tracking_generation_id, target_dataset_release_id)`
identifies one persistent and idempotent Tracking Advance. The Advance is
terminal only when it succeeds:

```text
pending -> running -> succeeded
             |
             v
           blocked -> running
```

Each execution is a Tracking Advance Attempt with
`queued -> running -> succeeded | failed | cancelled`. A failed or cancelled
Attempt leaves the Advance blocked and retryable under the same identity;
another Attempt may run without creating another user-visible Advance. A
successful Attempt atomically succeeds the Advance and publishes one immutable
Tracking Checkpoint.

Every Checkpoint manifest binds its Tracking Generation, target Dataset
Release, processed Research Session range, seed-definition and semantics
hashes, DailyTrack-pinned Numeric Execution Contract, Generation-pinned
calculation-kernel semantic version, runtime build identity, newly appended
Alpha and Label artifacts, Strategy events and state, and result checksums. A
normal Checkpoint's predecessor must belong to the same Generation. A
Generation root instead has
`predecessor = none`; ADR-0103 defines Generation 0's Activation root and
ADR-0107 defines a corrected Generation's replay root. A mutable Tracking Head
is only a pointer to the latest successful Checkpoint, never the result truth.

Dataset Publication commits a Dataset Release before it triggers active
DailyTracks and never waits for Tracking. An Advance failure leaves the previous
Checkpoint and Head unchanged, does not fail the Dataset Release, and does not
affect another DailyTrack. The failed frontier remains visible as lag and must
succeed before that Generation advances farther; deterministic data or
equivalence failures cannot be skipped. Stopping a DailyTrack prevents new
Advances and automatic retry Attempts; it never deletes the blocked Advance or
changes already published truth.

When workers lag behind multiple real Dataset Releases, they process those
releases in predecessor order. When one catch-up Dataset Release contains
multiple previously unpublished Research Sessions, a single Advance processes
every included session chronologically and emits each session's observations,
all bound to the real catch-up release. It never invents intermediate Dataset
Release identities.
