---
status: accepted
---

# Refresh market data through a private operator overlap merge

Data mutation is a private operator capability and is not exposed through the
ordinary user product API or Web interface. V1 has no automatic post-close
schedule. An operator explicitly starts or retries one asynchronous Data
Refresh through the private operations surface, while users see only the
current Dataset Head's coverage, data-through session, refresh time, and
readiness.

After bootstrap, each refresh requests the current latest session, the nineteen
preceding Research Sessions, and every newly completed session from Tushare.
For an already stored overlap key, a returned normalized value replaces the
current value, an absent value preserves the current value, and explicit
governing trading-state or lifecycle evidence takes precedence and invalidates
any conflicting stored price or turnover observation. Only ordinary absence
without that governing evidence preserves the current value. Newly completed
sessions have no prior values to preserve and must pass complete calendar,
instrument, price, adjustment, trading-state, and limit validation.

A refresh recomputes each derived Adjusted Research Price whose same-session
raw price or factor changed, plus every Liquidity Universe value affected by
the merged window. Appending a later factor never rescales an earlier price.
The operator validates the candidate Data Generation and moves the Dataset
Head atomically. It neither compares values to publish a correction log nor
notifies users that an overlap value changed.
A failed or incomplete candidate leaves the current Head unchanged, and a
later operator refresh may append several missed sessions in one Generation.

Financial data remains outside the implemented V1 Dataset Scope; its accepted
Point-in-Time semantics are unchanged and no financial refresh window is added
by this decision. There is no user-facing Data Update, Dataset Publication
entrypoint, correction log, or immutable Release chain. Independent
source-normalization, adjustment, trading-state, and validation rules remain.
