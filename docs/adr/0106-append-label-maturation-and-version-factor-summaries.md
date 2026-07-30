---
status: superseded by ADR-0148
---

# Append Label Maturation and version Factor summaries

For a signal session `t` and horizon `h`, the Label maturity frontier is its
nominal exit Research Session `t+1+h`:

```text
1-session Label:  t+2
5-session Label:  t+6
20-session Label: t+21
```

When a target Dataset Release first includes that nominal exit session, V1
resolves the Label in this order:

1. a full-session-suspended or terminally delisted entry coordinate produces
   `confirmed_market_open_unavailable`;
2. after a valid entry, terminal delisting effective on or before the nominal
   exit produces the valid Label `-100%`;
3. a full-session-suspended exit produces
   `confirmed_market_open_unavailable`;
4. a valid exit Open produces the ordinary Forward Return Label; and
5. any other missing or invalid required Open is a hard data-quality failure.

The observation remains pending before the maturity frontier even when an
eventual unavailable outcome could be inferred earlier. This preserves one
fixed maturation schedule and the 502, 498, and 483 standard-window bounds.

Resolution appends an immutable Label Maturation event containing
`generation_id`, signal session, horizon, effective maturity session,
originating Alpha observation, computed Label or governed missing reason,
`basis_dataset_release_id`, and publishing Checkpoint. The basis Release is the
actual target Release of the Advance, including an ADR-0144 correction-boundary
Advance. It never edits the seed Result Bundle or an earlier matured or
right-censored observation and never invents a historical Release identity for
a catch-up.

A pending Label that first reaches maturity at a correction boundary is a new
observation and resolves against that Advance's target Release. Previously
matured Labels remain unchanged. A new Factor Summary Snapshot is built from
the retained immutable observation sequence plus observations first published
by the current Advance; it does not recompute old observations from the latest
corrected Release.

The newly mature Label may append the corresponding daily IC, Rank IC,
Five-Quantile, and Top-Bottom observations under their existing sample rules.
Each successful Tracking Advance publishes a new immutable Factor Summary
Snapshot per horizon over the latest 504 signal sessions at that Checkpoint.
The snapshot includes only observations mature and valid as of its target
release; older observations that leave the 504-session window remain stored
but no longer enter the current summary.

The original ResearchRun Result Bundle and every earlier Tracking Checkpoint
remain unchanged. A user-visible current Factor view resolves through the
Tracking Head to the latest Summary Snapshot rather than updating an old
report in place.
