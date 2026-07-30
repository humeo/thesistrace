---
status: accepted
---

# Require one post-execution holding interval for a Rebalance

A scheduled Strategy signal creates orders only when both of these opens exist
inside the reported Research Window:

1. its `t+1` execution open; and
2. its `t+2` next valuation open.

For Research Sessions `R1` through `R504`, `R502` is therefore the latest
possible Strategy signal. If it is on the frozen Rebalance schedule, its orders
execute at the `R503` open and its resulting holdings are valued at the `R504`
open. A signal at `R503` does not execute at `R504`, because no reported
post-execution holding interval remains. It is skipped rather than queued.

At `R504`, V1 performs Terminal Valuation without a Rebalance and records the
final Strategy Daily Observation plus Terminal Strategy State. It does not
retain target-weight or diagnostic-event histories, force liquidation, or add
hypothetical exit costs.

This Strategy cutoff does not remove Alpha Values from Factor Evaluation.
Factor Evaluation retains every signal session in the Research Window and
applies its existing horizon-specific Forward Return Label availability rules.

This cutoff applies to a finite standard ResearchRun. ADR-0104 does not apply a
moving terminal cutoff to an active DailyTrack. At activation, a seed
post-close signal whose execution Open is still in the future may become the
pending Tracking signal; a signal whose execution Open already passed inside
the seed window remains skipped. Each later Tracking signal waits for its
future Open without requiring another Open already to exist.
