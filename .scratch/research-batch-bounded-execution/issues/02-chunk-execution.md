# Execute shared Batch work Chunk first

**Status:** complete

Load each shared context slice once, execute the applicable Alpha work serially,
and release all slice-owned Data before loading the next Chunk.

## Acceptance

- No Batch path reads the complete Calculation Period into one resident model.
- Factor item failures remain local; shared input failures fan out once.
- Strategy execution includes held instruments while keeping each read bounded.

## Comments

- 2026-09-03: Implemented and committed in `141594d`, with the bounded-memory
  sizing correction in `15f2673`. Factor execution now owns the global Chunk
  loop and releases Chunk-owned Arrow and matrix state before advancing. The
  full release gate passed at `d2adced`.
