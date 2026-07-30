---
status: accepted
---

# Report Gross and Net NAV from one fill path

Every V1 Strategy Backtest retains two NAV series from the same Actual Holdings,
Execution Share Quantities, Adjusted Holding Units, orders, and fills:

- Gross NAV values that same fill path before Transaction Costs; and
- Net NAV deducts commission, transfer fees, and stamp duty from that same
  path.

Net NAV is the primary Strategy result and the only Strategy NAV compared with
the Strategy Benchmark. Gross NAV is a cost-attribution view, not a second
cost-free Strategy run whose larger cash balance can generate different order
quantities. The report also exposes cumulative Transaction Costs so the
difference is auditable. In the real-number model, Gross and Net Cash differ
only by cumulative costs; both value positions as defined by ADR-0070.
ADR-0109's finite decimal execution may add a deterministic last-digit
rounding residual, which is not relabeled as Transaction Cost or corrected
through a balancing account. ADR-0056 defines cumulative and annualized
returns for both series.

Both series start from the same all-cash Initial Cash baseline defined by
ADR-0079. Initial-deployment Transaction Costs appear in the first Net Return
interval and are not removed before that baseline.

ADR-0081 makes Net Cash and Net NAV the only accounting state used for target
sizing, order sizing, affordability, and actual weights. Gross values never
feed a Strategy decision.

ADR-0099 commits both complete NAV series and their supporting result objects
inside the immutable ResearchRun Result Bundle before the Run can succeed.
