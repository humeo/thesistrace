# Research Batch bounded execution

**Status:** complete

Research Batch execution must share Data, Universe, Labels, and shared Alpha work
inside bounded execution Chunks without making Chunks durable Product State. Peak
resident memory is bounded by the frozen Chunk plan plus bounded continuation,
not by total Research Period length. Only a complete private Alpha-and-Factor
artifact and complete Result Bundles cross the durable publication boundary.

The change is a hard cut: the child protocol and private artifact schema have one
current version, with no compatibility reader, migration, or fallback path.

## Acceptance

- Dynamic-Universe long-history Batches are admitted and executed with bounded
  per-Chunk reads and memory.
- Factor items share each loaded Chunk; Strategy items consume one streamed
  artifact Chunk and matching Data slice at a time.
- Transient crashes retry at complete Alpha/Strategy granularity, while resource
  exhaustion and deterministic failures do not retry unchanged work.
- Equivalent ordinary ResearchRuns and Research Batch items publish canonically
  equivalent results.

## Comments

- The approved design intentionally keeps Chunk and continuation state ephemeral.
