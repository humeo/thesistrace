---
status: accepted
---

# Make module-first Core the only active runtime

ThesisTrace will first close one deployment-neutral product loop across Data,
Research Definitions, ResearchRuns, and DailyTracks. The active implementation
is a module-first modular monolith with one PostgreSQL Product State, immutable
S3-compatible storage, PostgreSQL-claimed workers, a pure Research Kernel, and
one Web product interface; it has no Local/Hosted mode, SQLite product runtime,
Temporal, event bus, custom object-store server, login, tenancy, or Hosted
dependency. This accepts concrete PostgreSQL coupling inside private atomic
admission interfaces in exchange for stronger locality and avoids shallow
ports where no second implementation exists.

Run saves the current mutable Research Definition and either returns validation
issues without creating a ResearchRun or atomically admits a queued ResearchRun
with frozen research and calculation contracts. Each execution Attempt selects
and pins the then-current Data Generation. A Rerun is a distinct ResearchRun
whose Attempt also selects current data when it starts. ResearchRun may
atomically activate one DailyTrack, after which that Track owns its complete
Tracking Origin and advances later Research Sessions independently. PostgreSQL
makes lifecycle and publication references authoritative; S3 holds
content-addressed Result and Checkpoint bytes that become visible only after
the matching PostgreSQL transaction commits.

The complete target shape and accepted interfaces are recorded in
[`docs/architecture/core.md`](../architecture/core.md). Implementation is not
complete merely because this ADR is accepted; the default Core gate must prove
the real PostgreSQL, real S3-compatible storage, worker, HTTP adapter, and
desktop browser loop before the old runtime is removed.

## Consequences

- Hosted V2 is preserved through an explicit Git archive ref before removal
  from the active tree. Its implementation and deployment decisions are
  historical inputs, not current Core constraints.
- The current Core has no User, tenant, membership, Workspace, identity, or
  hosted deployment model. Its four resources belong to the one running
  product instance.
- Existing quantitative and immutable-result decisions remain in force unless
  explicitly changed by a later accepted decision. The current Data Head,
  user-selected Research Period, Result budget, and private Refresh rules are
  defined by ADR-0153 through ADR-0156.
- The product keeps a hard limit of ten active or blocked DailyTracks without a
  quota or tenant abstraction.
- Historical Hosted implementation and deployment decisions have no authority
  over Core. Their recoverable snapshot exists only at the documented archive
  ref.
