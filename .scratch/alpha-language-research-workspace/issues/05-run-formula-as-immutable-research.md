# 05 — Run a Formula as immutable Research

**What to build:** Accept a complete Draft directly through the backend, execute its
compiled Alpha Expression through the Worker, and publish one durable Research result
without a Research Definition, Revision, or product-level Rerun.

**Blocked by:** 02 — Unify the Series Execution Plan; 03 — Author one Browser Draft in the Default Folder

**Status:** complete

- [x] Direct ResearchRun admission validates request shape, compiles the exact Formula, checks budgets and Data availability, and performs no durable mutation on rejection.
- [x] Formula or admission rejection returns structured `422` issues whose Alpha diagnostic code and source range match preview diagnostics.
- [x] Accepted admission atomically creates one queued ResearchRun with a unique request ID and returns `202`.
- [x] Retrying the same request ID with the same payload returns the same Run; reusing it with a different payload conflicts; concurrent delivery creates one Run.
- [x] Immutable Run input freezes Formula source, compiled Alpha Expression, Hypothesis, requested dates, canonical field bindings, Universe, neutralization, Strategy parameters, calculation contracts, and required Data admission facts.
- [x] Research name and Folder membership remain mutable columns outside immutable input; an empty name receives `Research <short-run-id>`.
- [x] The Worker executes only the stored ThesisTrace Alpha Expression and never recompiles Formula source or reads browser/Folder state.
- [x] Existing durable claim, Attempt retry, cancellation, Dataset Generation pinning, publication, provenance checksum, and result contracts remain green.
- [x] Research list and detail HTTP contracts expose status, name, Folder, creation time, Formula summary, frozen authorable input, and existing result detail.
- [x] The backend Definition CRUD/run and product rerun contracts are absent from the active HTTP interface and fresh schema after the hard cut.
- [x] End-to-end backend acceptance proves `Formula -> admission -> queued -> Worker -> succeeded result` against real PostgreSQL and object storage.

## Comments

- This ticket is the backend hard-cut tracer bullet. It is API-demoable through a complete published result before browser Run wiring lands.
- Verification: Python regression passed 387 tests; frontend typecheck and 13 component tests passed; fresh isolated PostgreSQL/RustFS integration run `20260812t174514z-37911-081e3d0a` passed 110 tests plus one database-restart test, and cleanup succeeded.
- Review: Standards and Spec reviews both passed on frozen staged SHA `080ad4ab4a14918d801e2807e9e21e7653acbbb3de07474c7bfcf4b66d41ed97` with no material findings.
