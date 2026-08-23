---
status: accepted
---

# Execute ResearchRun in contiguous full-Universe session chunks

ResearchRun admission deterministically divides the ordered Calculation
Warm-up and Research Period into contiguous Research Session chunks whose size
fits the Estimated Peak Execution Footprint. The selected chunk boundaries are
frozen with the execution plan so every infrastructure Attempt for the Run uses
the same boundaries.

Each session inside a chunk contains the complete eligible selected Universe.
Cross-sectional operators such as `rank` therefore execute against one
complete session cross-section and cannot use an instrument shard as a semantic
or checkpoint boundary. An implementation may parallelize work inside that
boundary only when the published numeric semantics remain exact.

Chunks execute in session order and a ResearchRun Execution Checkpoint advances
only after a complete chunk succeeds. A retry resumes at the next uncompleted
chunk under ADR-0195. Chunk boundaries cannot change Alpha, Factor, Strategy,
or Result values; ADR-0102 and ADR-0108's exact Batch-Incremental Equivalence
remains mandatory.

This refines ADR-0164's execution slice into one bounded ResearchRun Execution
Chunk rather than one whole-Research-Period materialization. It uses the same
Alpha planner and Builtin definitions rather than introducing a second engine
or versioned execution path.
