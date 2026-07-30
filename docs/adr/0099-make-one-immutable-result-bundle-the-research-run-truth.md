---
status: accepted
---

# Make one immutable Result Bundle the ResearchRun truth

Each successful ResearchRun publishes one immutable structured Result Bundle
as its authoritative result. Its Result Manifest identifies the ResearchRun,
the frozen Research Definition version and content hash, the Dataset Release,
the research-semantics version, Numeric Execution Contract,
calculation-kernel semantic version, runtime build identity, and the identities
and checksums of the required Factor Evaluation, Strategy Backtest,
time-series, event, and diagnostic result objects.

The user-visible report and UI are derived views of that bundle. They are not
independent result stores and cannot silently contain values absent from the
structured result.

A ResearchRun becomes `succeeded` only after all required Factor Evaluation
and Strategy Backtest objects and the final manifest are committed as one
complete publication. A failed or cancelled run may retain attempt diagnostics,
but incomplete result objects are not exposed as a successful partial report.
Published Result Bundles are immutable; a user rerun creates another
ResearchRun and another bundle.

A DailyTrack may reference a successful seed Result Bundle when creating its
Activation Checkpoint under ADR-0103, but it never extends or mutates that
bundle. ADR-0105 gives Daily Tracking its own immutable Checkpoint chain and
authoritative Head.
