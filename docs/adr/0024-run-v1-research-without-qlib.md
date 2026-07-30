---
status: accepted
---

# Run V1 research without Qlib

ThesisTrace V1 does not depend on Qlib, generate a Qlib Provider, maintain Qlib
`.bin` data, or implement a custom Qlib adapter. ResearchRun reads Canonical
Market Data from its pinned Dataset Release, while ThesisTrace owns the bounded
Alpha expression evaluation, Factor Evaluation, and daily Strategy Backtest
semantics required by the confirmed A-share end-of-day scope.

This avoids a second physical data format, conversion pipeline, cache, and
Qlib-specific price and volume coordinates. In exchange, ThesisTrace must
implement and verify its own research calculations and portfolio simulation.
Qlib investigations remain comparative research evidence, not a V1 runtime
contract.
