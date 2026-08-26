# Scale Research concurrency with single-slot Workers

Each Research Worker owns one execution slot and at most one supervised ResearchRun Attempt, whose Chunks execute sequentially within one declared resource envelope. Horizontal replicas provide concurrency; one Run is never split across Workers and a child never publishes Product State or survives its Attempt.
