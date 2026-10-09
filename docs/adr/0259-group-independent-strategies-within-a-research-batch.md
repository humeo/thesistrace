---
status: accepted
---

# Group independent Strategies within a Research Batch

An independent_strategies Batch may contain explicitly listed independent Strategies, including formula and Python authoring and Framework and Direct Strategies, while sharing one Research Period, Liquidity Universe, and Data Generation; multiple Alpha sweeps continue as separate submissions of the existing one-Alpha/multiple-configuration form, without a new Cartesian-product input. Each item owns its accepted inputs and applicable Industry Neutralization choice, so compatible dependencies determine reuse rather than requiring one Alpha or authoring mode across the entire Batch; each account and Result remains independent. This extends the shared-scope definition in ADR-0216 while retaining atomic admission, whole-Batch cancellation and recovery of complete tasks.

The independent path advances accounts inside a shared bounded input window. Reuse follows the normalized Alpha and neutralization identity under the same Generation, period, universe and numerical/semantic contracts. Python programs retain separate computation and state. Accounts and their retained state are included in capacity admission; one active numerical outcome is consumed at a time. Per-item live progress is observational, not a persistent checkpoint.

Recovery preserves complete published Strategy Results and recomputes unfinished complete Strategy tasks. This fused path does not materialize every full-history Alpha as a private artifact: doing so would require a second input traversal for accounts. Existing strategy_sweep keeps its durable complete shared Alpha prerequisite and serial account recovery. There is no cross-Batch cache or automatic Cartesian-product contract. The schema transition is explicit migration 0007; old records remain intact.

See [user authoring guide](../research-batches.md) for the public contract and [database upgrades](../database-migrations.md) for migration boundaries.
