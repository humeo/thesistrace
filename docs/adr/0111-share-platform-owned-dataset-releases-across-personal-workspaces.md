---
status: accepted
---

# Share platform-owned Dataset Releases across Personal Workspaces

The hosted platform operates one Tushare ingestion and Dataset Publication flow
and exposes each resulting immutable Dataset Release read-only to every Personal
Workspace. Personal Workspaces reference Releases but cannot own, modify, or
publish them; their private ownership begins with Research Definitions and
continues through ResearchRuns, DailyTracks, Results, and usage. This avoids
duplicating identical market-data ingestion and storage on the initial 6-core,
12-GB deployment.

The deployment premise is that the platform's applicable Tushare authorization
permits this hosted, multi-User use of the shared source-derived Dataset
Releases. The platform does not repeat ingestion per Workspace or reopen data
licensing as a per-User architecture decision.
