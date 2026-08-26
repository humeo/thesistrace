# Resume infrastructure retries from private ResearchRun Checkpoints

A ResearchRun executes contiguous full-Universe session Chunks and may durably checkpoint only a verified contiguous boundary plus bounded continuation and staged result state. A fenced infrastructure retry resumes the latest checkpoint for the same input, Generation, and contracts; mismatches fail integrity, stale children cannot publish, and terminal outcomes make all private recovery state collectible.
