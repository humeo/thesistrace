---
status: accepted
---

# Author Python strategies with a bounded class SDK

Python authors implement one `Strategy.on_close(data, account)` subclass, or the
corresponding Framework stage base. The class is loaded only inside the pinned
WASI guest. Data and account observations are explicit inputs; helpers construct
one returned decision, and the shared simulation owns execution. `self.state`
is the only persisted user memory. Other class attributes are invocation-local.

History methods perform bounded guest-to-host reads against the frozen generation,
host decision date and visible candidates plus actual holdings. This supports
dynamic Python windows without static source inference, extra declaration forms,
network access or direct database authority. Both successful reads and returned
decisions are independently validated by the host. Failed calls publish neither
new strategy state nor partial decisions/read evidence.

The source-only authoring model replaces the function ABI, parameter JSON and
declared history windows. Web, HTTP, MCP, Batch and DailyTrack share the current
contract. There is no old-ABI runtime fallback or automatic data deletion. This
change does not change the database schema; existing incompatible research is
handled only by the explicit backed-up process described in
[database migrations](../database-migrations.md#explicit-research-contract-retirement).

The design preserves the execution and risk-composition boundaries in
[ADR-0250](0250-admit-strategy-programs-with-explicit-simulation-coordinates.md).
The public inputs, outputs, lifecycle and limits are specified in the
[Python SDK reference](../python-strategy.md). Actual reads use typed, bounded
Trading Event records with the same retention and ownership as execution evidence.
