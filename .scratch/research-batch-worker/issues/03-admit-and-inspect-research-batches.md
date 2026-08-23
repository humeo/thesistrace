# 03 — Admit and inspect Research Batches atomically

**What to build:** Let an API client atomically submit either an ordered Factor
Evaluation Batch or an ordered single-Alpha Strategy Sweep and immediately
inspect the durable Batch and its stable child ResearchRun identities, without
adding a Batch frontend.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] The public admission contract requires an explicit Research Batch Kind and accepts only factor_evaluation or strategy_sweep.
- [ ] Factor Evaluation admission accepts one through twenty ordered Factor items and rejects Strategy fields, empty input, and a twenty-first item.
- [ ] Strategy Sweep admission accepts exactly one shared Alpha plus one through twenty ordered Strategy parameter items; the shared Alpha does not consume the item limit and no Alpha-by-Strategy cross-product is inferred.
- [ ] One Batch freezes its Research Period, Liquidity Universe, Industry Neutralization choice, Numeric Execution Contract, Data Generation, and relevant semantic versions for every child Run.
- [ ] Every item requires a unique item_key, preserves its submitted ordinal, and receives a stable ordinary ResearchRun ID during admission.
- [ ] Every Formula is compiled and every common and per-item field is validated before admission commits; diagnostics identify the failing item_key and field and retain source-range information for Formula errors.
- [ ] Canonically equivalent Factor Expressions are rejected as duplicates with both conflicting item_key values, regardless of names, whitespace, or formatting.
- [ ] Duplicate Strategy parameter tuples are rejected with both conflicting item_key values.
- [ ] Admission capacity is evaluated for the complete Batch against the declared execution envelope before any Product State is created.
- [ ] The Batch, ordered Batch Items, admission receipt, Generation retention, and all child ResearchRuns commit atomically or none of them exist.
- [ ] Exact idempotent replay returns the same Batch and ordered child IDs; reuse of the request ID with different canonical input returns a conflict.
- [ ] Concurrent duplicate admission, transaction failure, restart after an uncertain response, and invalid or oversized requests cannot create duplicate or partial Batches, Runs, receipts, retentions, or Publication objects.
- [ ] Child Runs are initially placed in the stable Batch Research Folder but immutable Batch membership is recorded independently of Folder membership.
- [ ] A Batch owns orchestration and ordered membership but owns no combined Result; each child Run retains its ordinary immutable input and future Result ownership.
- [ ] Batch-owned ResearchRuns are structurally ineligible for ordinary Research Worker claiming from the moment admission commits.
- [ ] Cursor listing and detail can return the newly admitted queued Batch with its frozen scope and ordered item-to-Run mapping; child Results are not embedded.
- [ ] No Batch DELETE route, compatibility payload, mixed-kind Batch, legacy alias, migration reader, fallback queue, or frontend Batch surface is introduced.

## Comments

- Parent: Research Batch Worker.
- This is the durable backend admission slice; execution begins in later tickets without a temporary executor.
