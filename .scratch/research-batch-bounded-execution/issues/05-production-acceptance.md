# Qualify bounded Batch execution and repair stuck work

**Status:** complete

Run the final Production Image under the 2 GiB Worker boundary, compare equivalent
ordinary and Batch results, then close only the two verified stuck Strategy
Batches and submit fresh equivalents.

## Acceptance

- The 11-year rotating Top300 Factor and Strategy scenarios complete without OOM.
- RSS remains bounded per Chunk and the Batch Worker remains stable.
- Exact-ID repair releases pins and scratch without modifying terminal audit data.

## Comments

- 2026-09-03: The clean Production Image gate passed at `d2adced` with a
  1.5 GiB child execution budget, 187,011,072-byte measured Batch peak RSS,
  semantic result equivalence, crash-restart verification, and zero Product
  State after reset.
- 2026-09-03: Repaired only `batch_ea77c1d1361541bc9f83` and
  `batch_184d9c11ad6e4f60ae3d`. Their original Attempts and six unfinished child
  Runs are terminal `failed/resource_exhausted`, both Generation pins and both
  Batch retentions are released, and the terminal audit Factor Batch
  `batch_3ab0bf3b6bec455aa095` remains unchanged.
- 2026-09-03: Qualified the exact Development Dataset Head
  `3bc1e66cdfe2dd11721965925a4514868568b1dcfd388cce6db3ffce5c7d96b4`
  over `2015-01-05..2026-08-14`, rotating Top300, with a 2 GiB/2 CPU Batch
  Worker and 1.5 GiB child budget. Factor Batch
  `batch_9216f037d22642509b64` completed 3/3 items in one Attempt with a
  386,007,040-byte peak child RSS. Momentum Strategy Batch
  `batch_fa96bdff68334aeba4c2` completed 3/3 in one Attempt with 44 shared
  Alpha-and-Factor Chunks, 135 Strategy Chunks, and a 401,891,328-byte peak.
  Quality Strategy Batch `batch_2f0ebec32a4d4e179f2b` completed 3/3 in one
  Attempt with the same Chunk counts and a 395,902,976-byte peak. Both child
  processes exited zero and acknowledged completion; the Worker was not OOM
  killed or restarted.
- 2026-09-03: The first live comparison exposed a Chunk-boundary-dependent
  Decimal accumulation order in Strategy position valuation. `2ee6f30` adds
  the failing regression and makes valuation use stable instrument order under
  the 34-digit accounting context. After redeployment, all six Strategy child
  Results from the two Batches are canonically identical to ordinary
  ResearchRuns `run_8fee0d864c564052b71e`, `run_95e4b953b6be4bdd8b87`,
  `run_0d881595981b405c90b8`, `run_fc39b067a23741c4b89e`,
  `run_25351eaf21274422a054`, and `run_5587accafccb4ff9ada0`.
  Together with the three Factor comparisons, all nine pairs match in complete
  calculation payload, public semantic result, contracts, semantic versions,
  and Generation. All run/batch pins and retentions are released, the Batch
  scratch volume is empty, and there are no active Batch or ResearchRun rows.
