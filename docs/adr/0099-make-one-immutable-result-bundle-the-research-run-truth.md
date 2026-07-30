---
status: accepted
---

# Make one immutable Result Bundle the ResearchRun truth

Each successful ResearchRun publishes one immutable structured Result Bundle
as its authoritative result. Its Result Manifest identifies the ResearchRun,
the frozen Research Definition version and content hash, the Dataset Release,
the research-semantics version, Numeric Execution Contract,
calculation-kernel semantic version, runtime build identity, and the identities
and checksums of its bounded Factor summaries and retained minimal Strategy
results. The Strategy result consists of its bounded daily account series,
per-Rebalance aggregates, daily cost and rejection aggregates, and terminal
account and position state. Alpha Matrix values, Forward Return Labels, daily
Factor observations, raw orders and fills, and detailed event or diagnostic
streams are runtime intermediates rather than Result Bundle objects.

The user-visible report and UI are derived views of that bundle. They are not
independent result stores and cannot silently contain values that are neither
stored in nor deterministically derivable from the structured result under its
pinned semantics.

A ResearchRun becomes `succeeded` only after every required bounded summary,
retained Strategy object, and the final manifest are committed as one complete
publication. The combined size of all immutable result payloads owned by one
ResearchRun, including its manifest, must not exceed 1 MiB; referenced Dataset
Release objects and shared runtime artifacts are not copied into that budget. A
failed or cancelled run may retain bounded attempt diagnostics, but incomplete
result objects are not exposed as a successful partial report. Published Result
Bundles are immutable; a user rerun creates another ResearchRun and another
bundle.

A DailyTrack may reference a successful seed Result Bundle when creating its
Activation Checkpoint under ADR-0103, but it never extends or mutates that
bundle. ADR-0105 gives Daily Tracking its own immutable Checkpoint chain and
authoritative Head.
