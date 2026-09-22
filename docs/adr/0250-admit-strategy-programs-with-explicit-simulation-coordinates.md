---
status: accepted
---

# Admit Strategy Programs with explicit simulation coordinates

The next Strategy contract admits Python Direct Strategies and Framework Strategies composed from built-in or Researcher-authored decision modules, using one daily decision interface and explicit resumable state while the platform retains execution, fees, slippage, valuation and bookkeeping. Each selected Strategy produces one final Target Decision after its internal portfolio and risk policies, using completed-session information to freeze portfolio weights or position-local changes for the following Open; only shared Execution creates orders, and post-Open performance remains separate from Close Risk NAV. Isolated execution, bounded state and session-scoped data access are required for both Python modes, accepting those costs to support custom strategy decisions without granting authority over future data, simulated fills or account records.

## Implementation status

Accepted on 2026-09-22 for the next Strategy contract; this is a design decision, not a claim of implementation. The checked implementation still provides the fixed score-based strategy, fixed fees and zero modeled slippage. The related execution ADRs describe this accepted extension, which must be delivered and verified through the shared Run, Batch and DailyTrack paths before cutover; QuantConnect API compatibility is not promised.
