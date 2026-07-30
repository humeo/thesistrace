---
status: accepted
---

# Start an explicit DailyTrack from a successful ResearchRun

`DailyTrack` is the stable identity of one continuous V1 Daily Tracking stream.
It is not a ResearchRun, and Dataset Publication does not create one
automatically. The operator may start a DailyTrack only from a `succeeded`
ResearchRun with a complete Result Bundle.

The DailyTrack permanently records its seed ResearchRun, frozen Research
Definition identity and content hash, resolved Field Catalog bindings, research
semantics, numeric contract, and Tracking Origin. Its Activation Dataset Release
is exactly the Dataset Release pinned by the seed ResearchRun; operator wall
clock time and the current `latest` release never change that coordinate. A
later edit, freeze, or rerun never changes an existing DailyTrack; tracking
changed Alpha, Strategy, execution, cost, or numeric semantics requires another
successful ResearchRun and a new DailyTrack.

Each Tracking Advance independently binds one later immutable Dataset Release.
Its effective computation identity is the pinned seed research semantics plus
that target release. This does not overwrite the Dataset Release stored in the
seed's frozen Research Definition and does not introduce a second research
format, compiler, or compiled plan.

Starting creates Tracking Generation 0 and its root Activation Checkpoint with
`predecessor = none`, pins the calculation-kernel semantic version recorded by
the seed Result Manifest, then initializes Tracking Head to that root. The
Activation Checkpoint references and reuses the seed Result Bundle's checksummed
Alpha Matrix and terminal accounting state. If later real Dataset Releases
already exist when the operator starts the Track, Advances catch up from the
seed Release through their predecessor order; activation never jumps directly
to current `latest`. User-visible Daily Tracking begins at activation, and V1
does not pretend that the historical sessions inside the seed run were
separately available DailyTrack updates.

A new DailyTrack is `active`. An operator may terminally change it to `stopped`,
which prevents new Advances and automatic retries without changing its Head or
published Checkpoints. V1 does not resume a stopped Track; any later tracking
request starts from another successful ResearchRun and new DailyTrack.
