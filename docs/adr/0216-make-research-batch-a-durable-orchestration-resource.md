# Make Research Batch a durable orchestration resource

A Research Batch atomically admits ordered ordinary ResearchRuns that share a
research scope and Data Generation, owns aggregate lifecycle and cancellation,
but owns no Result; every item retains its own immutable ResearchRun and Result.
Factor Batches share preparation across independent Alphas, while Strategy
Sweeps share one Alpha and Factor across enumerated Strategy inputs, and both
must exactly match equivalent ordinary Runs without implicit cross-products or
partial admission.

Batch execution is Chunk-first. Admission measures the actual member union of
each candidate execution slice and freezes one common Chunk size into every
child ResearchExecutionPlan. Peak resident memory is bounded by that Chunk,
its lookback and Label context, one active calculation, bounded Alpha and
Strategy continuation, one decoded private-artifact frame, and one Strategy
output buffer. Total Research Period length may increase elapsed work and disk
artifact size, but not the planned resident-memory peak. If one Research
Session cannot fit, admission rejects the complete Batch.

Chunk Data, Universe, Labels, continuation, partial output, and files ending in
`.partial` are Attempt scratch. They are neither domain resources nor recovery
checkpoints. A Strategy Sweep may durably publish only a complete, binding- and
checksum-validated private Alpha-and-Factor Artifact; each Strategy may publish
only a complete Result Bundle. Publication is atomic at those boundaries.

Worker or process loss and explicitly classified transient infrastructure
failure may create a new Attempt, up to three Attempts for the same incomplete
complete task. A new Attempt preserves already published Alpha/Strategy
outcomes, discards all ephemeral Chunk state, and recomputes the earliest
incomplete complete task. Resource exhaustion never retries the same frozen
execution plan. Invalid formulas, bad Data, invalid artifacts, and other
deterministic calculation failures are permanent. Starting claims count toward
the retry budget even if the child fails before allocating its first Chunk.
