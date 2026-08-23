# 05 — Execute Strategy Sweeps from one shared Alpha and Factor

**What to build:** Let the dedicated Batch Research Worker calculate one
Strategy Sweep's Data, Alpha, and Factor work once and then execute each ordered
Strategy parameter combination as an independent ordinary Strategy Backtest.

**Blocked by:** 02 — Recompose Strategy execution from the shared outcome; 04 — Execute Factor Evaluation Batches with shared preparation

**Status:** ready-for-agent

- [ ] A Strategy Sweep prepares its frozen Data once and completes exactly one shared Alpha-and-Factor task before any dependent Strategy task runs.
- [ ] The current Strategy calculation runs exactly once per submitted parameter tuple and in submitted ordinal order.
- [ ] No implicit Cartesian product, second Alpha, alternate Strategy algorithm, or server-generated parameter combination is accepted or executed.
- [ ] Every successful item publishes an ordinary self-contained Strategy Backtest Result containing the shared Factor Summary, that item's Strategy Summary, Strategy Daily Observations, and Terminal Strategy State.
- [ ] Every child Result carries its own correct ResearchRun identity and provenance even though its Factor calculation was shared.
- [ ] Against the same frozen Generation, each Batch item has exact Factor, Strategy, and terminal-state semantic checksums, calculation contracts, and semantic versions as the equivalent separately admitted ordinary Strategy Backtest.
- [ ] Stage and I/O evidence proves one Data preparation, one Alpha execution, one Factor execution, and one Strategy execution per submitted item.
- [ ] A permanent failure of the shared Alpha-and-Factor task fails every dependent Strategy Run without starting Strategy calculation.
- [ ] A deterministic failure of one Strategy parameter combination fails only that child Run and allows later Strategy items to continue.
- [ ] Successful, failed, and mixed outcomes derive the correct Batch aggregate state without creating a combined Batch Result or selecting a best parameter tuple.
- [ ] A successful child Strategy Run retains the ordinary ability to seed a DailyTrack, while Batch execution never starts tracking automatically.
- [ ] Strategy parameters cannot mutate the shared Alpha-and-Factor outcome or change the Factor Summary included in sibling Results.
- [ ] One-item and twenty-item Strategy Sweeps use the same contract, and the shared Alpha remains outside the item count.
- [ ] Peak child RSS remains inside the existing execution budget while shared work is retained for the active Sweep.
- [ ] The implementation reuses the formal Research Kernel seam and ordinary Publication contract; it adds no copied math, public shared artifact, permanent Alpha store, cross-Batch cache, second image, or Batch frontend.

## Comments

- Parent: Research Batch Worker.
- Durable cross-Attempt reuse of the shared prerequisite is added after the recovery boundary is established.
