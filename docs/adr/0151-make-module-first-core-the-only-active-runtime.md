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
issues without creating a ResearchRun or atomically embeds an immutable input
pinned to the latest Dataset Release in a new queued ResearchRun. A user Rerun
is a different ResearchRun with the original immutable input and Release.
ResearchRun may atomically activate one DailyTrack, after which that Track owns
its complete Tracking Origin and advances independently from later Releases.
PostgreSQL makes lifecycle and publication references authoritative; S3 holds
content-addressed immutable bytes that become visible only after the matching
PostgreSQL transaction commits.

The complete target shape and accepted interfaces are recorded in
[`docs/architecture/core.md`](../architecture/core.md). Implementation is not
complete merely because this ADR is accepted; the default Core gate must prove
the real PostgreSQL, real S3-compatible storage, worker, HTTP adapter, and
desktop browser loop before the old runtime is removed.

## Consequences

- Hosted V2 is preserved through an explicit Git archive ref before removal
  from the active tree. Its implementation and deployment decisions are
  historical inputs, not current Core constraints.
- Login and hosted deployment may be designed later as adapters around the
  accepted Core. They may not introduce a second product interface or restore
  the prior dependency graph by default.
- The current Core has no User, tenant, membership, Workspace, or identity
  ownership model. Its four resources belong to the one running product
  instance until the Hosted phase explicitly adds an ownership boundary.
- Existing quantitative and immutable-result decisions remain in force unless
  explicitly superseded. In particular, ADR-0122, ADR-0131, ADR-0132,
  ADR-0144, ADR-0146, and ADR-0147 remain active.
- ADR-0117's hard limit of ten active or blocked DailyTracks is retained, but
  its Personal Workspace quota model is not.
- ADR-0150 is retained only as deferred Hosted identity research; it does not
  add Auth Session or InsForge dependencies to Core.

## Superseded scope

This decision supersedes ADR-0005, ADR-0007, ADR-0015, ADR-0027, ADR-0096,
ADR-0098, ADR-0113, ADR-0115 through ADR-0118, ADR-0125, ADR-0126, ADR-0129,
ADR-0141, ADR-0145, ADR-0148, and ADR-0149. Hosted V2-specific decisions from
ADR-0110 through ADR-0143 that are not explicitly carried forward above are
superseded and retained only as history, not requirements for the active Core.
ADR-0150 remains an accepted but deferred Hosted identity decision and has no
authority over Core.
