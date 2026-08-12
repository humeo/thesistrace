# 05 — Run a Formula as immutable Research

**What to build:** Accept a complete Draft directly through the backend, execute its
compiled Alpha Expression through the Worker, and publish one durable Research result
without a Research Definition, Revision, or product-level Rerun.

**Blocked by:** 02 — Unify the Series Execution Plan; 03 — Author one Browser Draft in the Default Folder

**Status:** ready-for-agent

- [ ] Direct ResearchRun admission validates request shape, compiles the exact Formula, checks budgets and Data availability, and performs no durable mutation on rejection.
- [ ] Formula or admission rejection returns structured `422` issues whose Alpha diagnostic code and source range match preview diagnostics.
- [ ] Accepted admission atomically creates one queued ResearchRun with a unique request ID and returns `202`.
- [ ] Retrying the same request ID with the same payload returns the same Run; reusing it with a different payload conflicts; concurrent delivery creates one Run.
- [ ] Immutable Run input freezes Formula source, compiled Alpha Expression, Hypothesis, requested dates, canonical field bindings, Universe, neutralization, Strategy parameters, calculation contracts, and required Data admission facts.
- [ ] Research name and Folder membership remain mutable columns outside immutable input; an empty name receives `Research <short-run-id>`.
- [ ] The Worker executes only the stored ThesisTrace Alpha Expression and never recompiles Formula source or reads browser/Folder state.
- [ ] Existing durable claim, Attempt retry, cancellation, Dataset Generation pinning, publication, provenance checksum, and result contracts remain green.
- [ ] Research list and detail HTTP contracts expose status, name, Folder, creation time, Formula summary, frozen authorable input, and existing result detail.
- [ ] The backend Definition CRUD/run and product rerun contracts are absent from the active HTTP interface and fresh schema after the hard cut.
- [ ] End-to-end backend acceptance proves `Formula -> admission -> queued -> Worker -> succeeded result` against real PostgreSQL and object storage.

## Comments

- This ticket is the backend hard-cut tracer bullet. It is API-demoable through a complete published result before browser Run wiring lands.
