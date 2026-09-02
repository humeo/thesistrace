# Qualify bounded Batch execution and repair stuck work

**Status:** ready-for-agent

Run the final Production Image under the 2 GiB Worker boundary, compare equivalent
ordinary and Batch results, then close only the two verified stuck Strategy
Batches and submit fresh equivalents.

## Acceptance

- The 11-year rotating Top300 Factor and Strategy scenarios complete without OOM.
- RSS remains bounded per Chunk and the Batch Worker remains stable.
- Exact-ID repair releases pins and scratch without modifying terminal audit data.

## Comments
