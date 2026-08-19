# 03 — Resume and cancel long Factor Evaluation safely

**What to build:** Let a long historical Factor Evaluation progress through bounded
Chunks, survive retry and Worker loss, and cancel truthfully while retaining only
the execution state needed for Factor work and protecting its frozen Data
Generation.

**Blocked by:** 02 — Author and reuse Research Kinds without ambiguity

**Status:** complete

## Plan

1. Characterize Factor Evaluation specifically at the existing public ResearchRun,
   real Worker/child, PostgreSQL, RustFS, Checkpoint, and cancellation boundaries;
   reuse the current lifecycle rather than adding a Factor-only recovery path.
2. Add a multi-Chunk Factor Evaluation scenario that inspects durable progress and
   private Checkpoint publications, proving their frozen Kind/binding/checksum
   identity and the structural absence of Strategy continuation and observation
   descriptors.
3. Extend the existing transient retry, Worker-loss, restart, and stale-fence
   acceptance to Factor Evaluation, proving resume from the last committed Chunk
   under the same Run, Generation, FIFO position, and fixed execution plan, with
   no partial Result or leaked private state.
4. Extend queued/running cancellation coverage to Factor Evaluation, including
   cooperative and forced child exit, the five-second healthy-owner budget,
   pre-stage and late-publication fencing, truthful progress, and Pin/checkpoint
   cleanup only after child exit.
5. Fix only lifecycle defects exposed by those real-boundary tests; keep the one
   Research queue, Worker role, supervised child, Checkpoint engine, Publication
   path, retry taxonomy, and cancellation implementation shared by both kinds.
6. Run focused kernel and real-dependency acceptance gates followed by the
   repository fast gate, then complete independent Standards and Spec reviews,
   fix and re-review every material finding, mark the ticket complete, and create
   one Ticket 03 commit.

- [x] A long Factor Evaluation uses the existing capacity-planned fixed Research Execution Chunks and publishes durable committed progress after each accepted Chunk.
- [x] Factor-only continuation contains bounded Alpha, pending Forward Return Label, Factor aggregation, checksum, and progress state but no Strategy continuation or Strategy observation descriptors.
- [x] Every private Checkpoint is bound to Research Kind, frozen immutable input, Data Generation, calculation contracts, execution plan, Attempt fence, ordinal, payload descriptors, and chained checksum.
- [x] A retry resumes from the latest valid Factor-only Checkpoint under the same ResearchRun, admission position, Research Kind, Data Generation, and fixed plan.
- [x] Worker loss before a durable Chunk commit discards in-flight work and resumes from the last committed Checkpoint without publishing a partial Result.
- [x] Transient PostgreSQL or Publication failure follows the existing bounded automatic retry policy; permanent calculation, contract, integrity, and capacity failures retain their current terminal classifications.
- [x] Queued and running Factor Evaluation use the existing cancellation action and expose truthful queued, running, cancelling, and cancelled states.
- [x] Running cancellation fences late Checkpoint, staged payload, and Result publication and releases the Generation Pin only after child exit is confirmed.
- [x] A healthy owning supervisor completes confirmed cancellation within the existing five-second total budget.
- [x] Lost-supervisor recovery waits for the existing lease and ownership proof and never releases the Pin while the old child can remain alive.
- [x] A stale Attempt cannot win after another owner advances the fence, even if it already produced calculation output.
- [x] Successful publication, terminal failure, and cancellation clean private Checkpoints and retained staging ownership according to the existing lifecycle; retry preserves only the state required to resume.
- [x] Public progress distinguishes committed Research Sessions and Chunks from in-flight work and never presents transient work as durable progress.
- [x] Real process, PostgreSQL, RustFS, and Worker tests cover multi-Chunk success, transient retry, checkpoint resume, Worker loss, application and database restart, cooperative and forced cancellation, stale publication, and cleanup without arbitrary sleeps.

## Comments

- Extended the shared ResearchRun lifecycle tests to Factor Evaluation rather
  than introducing a kind-specific queue, Worker, retry, cancellation, or
  Publication implementation.
- Checkpoint provenance now names the frozen Research Kind explicitly in
  addition to the immutable-input hash, Generation, contracts, fixed plan,
  Attempt fence, ordinal, payload descriptors, and chained checksum.
- Real PostgreSQL, RustFS, Worker/child, application-reopen, and PostgreSQL
  restart acceptance verifies bounded Factor-only continuation, committed
  progress, checkpoint resume, transient retry, stale fencing, five-second
  cooperative/forced cancellation, Pin lifetime, and terminal cleanup.
- Review: independent Standards/Test Ruler and Spec reviews both passed with no
  material findings.
- Verification: focused kernel gates passed 28/28; isolated integration run
  `20260819t190122z-65012-4ec33ded` passed 192 ordinary tests plus the dedicated
  database-restart recovery test; `pnpm test` passed 523 Python tests, TypeScript
  type checking, and 37 frontend shell tests.
