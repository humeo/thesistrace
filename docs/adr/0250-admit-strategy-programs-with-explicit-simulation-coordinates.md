---
status: accepted
---

# Admit Strategy Programs with explicit simulation coordinates

The Strategy contract admits Python Direct Strategies and Framework Strategies composed from built-in or Researcher-authored decision modules, using one daily decision interface and explicit resumable state while the platform retains execution, fees, slippage, valuation and bookkeeping. Each selected Strategy produces one final Target Decision after its internal portfolio and risk policies, using completed-session information to freeze portfolio weights or position-local changes for the following Open; only shared Execution creates orders, and post-Open performance remains separate from Close Risk NAV. Isolated execution, bounded state and session-scoped data access are required for both Python modes, accepting those costs to support custom strategy decisions without granting authority over future data, simulated fills or account records.

## Implementation status

The current implementation admits Python Direct and built-in/custom Framework Strategies through the same ResearchRun, Batch and DailyTrack execution paths. Researcher programs run in the pinned CPython/WASI runtime with explicit bounded state; the platform owns account transitions and fills. Built-in holding/risk rules, configurable fees and fixed-basis-point slippage are implemented. Fees retain the existing defaults, minimum commission applies to each child order, and slippage defaults to zero. Decisions use completed-session data and execute at the next Open; Close Risk NAV remains separate from the primary Open performance series.

Deployment qualification and environment cutover are separate from implementation. Old research retirement is explicit, backed up and reference-scoped as described in [database migrations](../database-migrations.md#explicit-research-contract-retirement); it never runs at startup. QuantConnect API compatibility is not promised.
