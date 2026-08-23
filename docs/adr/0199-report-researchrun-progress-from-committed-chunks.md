---
status: accepted
---

# Report ResearchRun progress from committed chunks

Every successful ResearchRun Execution Chunk atomically advances durable
ResearchRun Progress with the completed Research Period session count, total
Research Period session count, last completed session, and current execution
phase. This committed boundary is the only completed-work truth, remains
monotonic across infrastructure Attempts, and resumes from the same value as the
validated Checkpoint.

A warm-up-only Checkpoint reports phase `warmup` and its own committed completed
and total Calculation Warm-up sessions. It leaves completed Research Period
sessions at zero and `last_completed_research_session` empty. Warm-up therefore
remains visibly live without being counted as completed research or provisional
Factor and Strategy output.

The active Attempt heartbeat may additionally expose its current phase and
currently processing Research Session for liveness. Heartbeat data never marks
that session complete and disappears with its Attempt. The UI distinguishes
committed progress from in-flight work and does not infer progress from elapsed
wall time.

After enough Chunks complete to establish observed throughput, ThesisTrace may
estimate remaining duration from that throughput and remaining Estimated Total
Research Work.
The value is labelled as an estimate, may be revised as later Chunks complete,
and is never a completion guarantee or admission boundary.

Progress exposes no Alpha Values, Factor observations, Strategy observations,
Staged Result Partitions, or provisional metrics. Partial computation remains
private until ADR-0099's final atomic Result publication.
