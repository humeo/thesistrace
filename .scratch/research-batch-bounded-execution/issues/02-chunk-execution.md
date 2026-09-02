# Execute shared Batch work Chunk first

**Status:** ready-for-agent

Load each shared context slice once, execute the applicable Alpha work serially,
and release all slice-owned Data before loading the next Chunk.

## Acceptance

- No Batch path reads the complete Calculation Period into one resident model.
- Factor item failures remain local; shared input failures fan out once.
- Strategy execution includes held instruments while keeping each read bounded.

## Comments
