---
status: accepted
---

# Use the selected Liquidity Universe as the Strategy Benchmark

Every Strategy Backtest compares its return with the daily equal-weight return
of the Liquidity Universe selected by the same frozen Research Definition. V1
does not silently use a default CSI 300 benchmark or require a separate
external-index dataset; aligning the comparison series with the selected Top
300, 1000, 2000, or 3000 opportunity set makes results comparable without
expanding the data scope.

For the Strategy holding interval associated with signal session `t`, the
Benchmark uses the Universe Membership snapshot determined after `t` closes
and the Adjusted Research Price return from the `t+1` open to the `t+2` open.
The return becomes known at the latter open. It never applies membership before
that membership is available. ADR-0053 defines benchmark treatment of confirmed
suspensions, and ADR-0055 defines the shared open-time NAV sequence.

ADR-0079 normalizes Benchmark NAV to 1 at the first Research Window open and
keeps it flat through the initial-deployment open. Its first market return is
the holding interval from the second to the third Research Window open.
