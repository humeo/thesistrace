# 19 — Keep DailyTrack forward-only across overlap corrections

**What to build:** Keep an existing DailyTrack's published simulated-account
history immutable when overlapping market data is corrected, while using the
corrected current Dataset for results first calculated in later sessions.

**Blocked by:** 10 — Refresh current data through a 20-session overlap merge; 17 — Start and catch up a DailyTrack from terminal state.

**Status:** ready-for-agent

- [ ] After a Track has published through session T, a successful Refresh that changes only T or earlier data and adds no session does not publish a new Checkpoint or move Tracking Head.
- [ ] Durable Checkpoints, cash, holdings, costs, NAV, Factor Summary Snapshots, and their identities published before Refresh remain byte-for-byte unchanged; raw orders and fills remain transient and no replay creates a new historical order or fill record.
- [ ] When a later Head first adds a session after T, Advance processes only unpublished sessions and uses the corrected values available in its pinned Generation.
- [ ] The controlled correction materially changes a later signal or Universe outcome, proving future calculation reads corrected data rather than merely proving history is unchanged.
- [ ] No correction notification, historical-diff resource, replay generation, or user-visible correction status is created.
- [ ] DailyTrack Factor Summary Snapshot continues to use the latest 504 signal sessions independently of ResearchRun length.
- [ ] Acceptance uses the real private Refresh path, an active Track, real PostgreSQL and RustFS, and a mounted store; it compares retained history before and after correction canonically.
