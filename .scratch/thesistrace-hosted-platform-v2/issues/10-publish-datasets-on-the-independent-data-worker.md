# 10 — Publish Datasets on the independent Data Worker

**What to build:** Execute each scheduled or Operator-requested Dataset
Publication as one durable finite Workflow on the dedicated Data Worker, then
make its immutable result available read-only without competing for User
Compute capacity.

**Blocked by:** 03 — Enforce the Hosted Tushare authorization gate; 06 — Isolate private research and share read-only Datasets; `thesistrace-bounded-research-storage/02 — Publish Canonical Dataset Releases as partitioned Parquet`.

**Status:** ready-for-agent

- [ ] A Temporal Schedule or authorized versioned Operator CLI command requests Dataset Publication through durable platform state and a stable Workflow identity.
- [ ] Only the one-slot Data Worker polls the Dataset Publication Task Queue, and two overlapping triggers cannot execute concurrent publication.
- [ ] Live Tushare work cannot start without the recorded hosted-use authorization declaration, while deterministic fixture publication remains available with the gate closed.
- [ ] A successful Workflow validates and atomically commits one immutable Dataset Release before recording durable Tracking trigger work; it does not wait for Personal Workspace Tracking Advances.
- [ ] A failed, cancelled, or redelivered publication leaves the previous Dataset Release authoritative and publishes no partial manifest or candidate object set.
- [ ] Dataset Publication follows the shared resource-exhaustion policy: the first exhausted Activity may retry once, a second ends with stable `RESOURCE_EXHAUSTED`, and neither execution can publish a partial Dataset Release.
- [ ] User APIs expose the resulting Dataset Release read-only, and no authenticated User route can invoke, mutate, or delete platform Dataset Publication.
- [ ] Dataset Publication consumes the independent Data slot and does not reduce the four-slot Compute capacity.
