# Claim ResearchRuns in strict FIFO order

Ordinary Research Workers claim the oldest eligible ResearchRun by admission time and stable identity using atomic PostgreSQL locking. Retries retain the Run's original order, while estimated work never introduces priority, shortest-job-first scheduling, or a second scheduler.
