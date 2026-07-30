---
status: accepted
---

# Use one default Quota Profile with Personal Workspace overrides

ThesisTrace sets the deployment-neutral Active DailyTrack Limit to `10`, applying it to the V1 Workspace and as the hard maximum for each hosted Personal Workspace; a Hosted Quota Profile override may only lower it. Every Personal Workspace also receives `max_nonterminal_user_compute_jobs = 8` and `max_private_storage_bytes = 10 GiB`, with auditable overrides and no billing tiers. These limits govern only new admissions and writes without canceling running work, deleting immutable history, or charging platform-owned resources to a Personal Workspace.
