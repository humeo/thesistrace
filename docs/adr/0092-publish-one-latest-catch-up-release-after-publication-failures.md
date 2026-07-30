---
status: accepted
---

# Publish one latest catch-up release after publication failures

If one or more normal post-close Dataset Publication attempts fail, the
previous latest Dataset Release remains available. The next successful attempt
publishes one atomic catch-up release ending on the latest newly completed
Research Session and containing every required intervening session.

V1 does not retrospectively create separate Dataset Releases for the missed
session end dates. Those snapshots were not successfully fetched and validated
at their original publication times, so creating them later would falsely
represent them as formerly available releases.

For example, if releases for Tuesday and Wednesday fail and Thursday succeeds,
one Thursday-ending release supersedes Monday's latest release. No Tuesday- or
Wednesday-ending release is manufactured afterward.

ADR-0105 requires a DailyTrack to process Tuesday, Wednesday, and Thursday in
session order inside one Thursday-bound Tracking Advance. The resulting
observations keep their individual session dates but all identify the one real
Thursday catch-up Dataset Release.
