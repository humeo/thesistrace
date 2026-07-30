# 21 — Manage Tracking frontiers, retries, and catch-up

**What to build:** Keep each active DailyTrack ordered and recoverable when
workers fail, Releases accumulate, catch-up publication spans multiple sessions,
or the operator stops tracking.

**Blocked by:** 06 — Publish incremental, catch-up, and correction Releases; 17 — Harden ResearchRun lifecycle; 19 — Advance a DailyTrack by Research Session.

**Status:** ready-for-agent

- [ ] Advance Attempts follow queued, running, and terminal success, failure, or cancellation independently of the persistent Advance.
- [ ] Failed or cancelled Attempts leave one blocked, retryable Advance under the same identity.
- [ ] A blocked frontier remains visible as lag and later target Releases cannot skip it within that Generation.
- [ ] Real Releases process in predecessor order when a Track is behind.
- [ ] One catch-up Release processes every included Research Session chronologically inside one Advance and binds every observation to that real Release.
- [ ] Stopping prevents new Advances and automatic retries without deleting blocked work or published Checkpoints.
- [ ] Worker restart and duplicate delivery preserve one Advance and at most one successful Checkpoint per identity.
