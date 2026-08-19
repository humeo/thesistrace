# 03 — Resume and cancel long Factor Evaluation safely

**What to build:** Let a long historical Factor Evaluation progress through bounded
Chunks, survive retry and Worker loss, and cancel truthfully while retaining only
the execution state needed for Factor work and protecting its frozen Data
Generation.

**Blocked by:** 02 — Author and reuse Research Kinds without ambiguity

**Status:** ready-for-agent

- [ ] A long Factor Evaluation uses the existing capacity-planned fixed Research Execution Chunks and publishes durable committed progress after each accepted Chunk.
- [ ] Factor-only continuation contains bounded Alpha, pending Forward Return Label, Factor aggregation, checksum, and progress state but no Strategy continuation or Strategy observation descriptors.
- [ ] Every private Checkpoint is bound to Research Kind, frozen immutable input, Data Generation, calculation contracts, execution plan, Attempt fence, ordinal, payload descriptors, and chained checksum.
- [ ] A retry resumes from the latest valid Factor-only Checkpoint under the same ResearchRun, admission position, Research Kind, Data Generation, and fixed plan.
- [ ] Worker loss before a durable Chunk commit discards in-flight work and resumes from the last committed Checkpoint without publishing a partial Result.
- [ ] Transient PostgreSQL or Publication failure follows the existing bounded automatic retry policy; permanent calculation, contract, integrity, and capacity failures retain their current terminal classifications.
- [ ] Queued and running Factor Evaluation use the existing cancellation action and expose truthful queued, running, cancelling, and cancelled states.
- [ ] Running cancellation fences late Checkpoint, staged payload, and Result publication and releases the Generation Pin only after child exit is confirmed.
- [ ] A healthy owning supervisor completes confirmed cancellation within the existing five-second total budget.
- [ ] Lost-supervisor recovery waits for the existing lease and ownership proof and never releases the Pin while the old child can remain alive.
- [ ] A stale Attempt cannot win after another owner advances the fence, even if it already produced calculation output.
- [ ] Successful publication, terminal failure, and cancellation clean private Checkpoints and retained staging ownership according to the existing lifecycle; retry preserves only the state required to resume.
- [ ] Public progress distinguishes committed Research Sessions and Chunks from in-flight work and never presents transient work as durable progress.
- [ ] Real process, PostgreSQL, RustFS, and Worker tests cover multi-Chunk success, transient retry, checkpoint resume, Worker loss, application and database restart, cooperative and forced cancellation, stale publication, and cleanup without arbitrary sleeps.
