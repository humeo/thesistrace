# 17 — Start and catch up a DailyTrack from terminal state

**What to build:** Start one explicit DailyTrack from a successful dated Run's
terminal simulated account and catch it up session by session to the current
Dataset Head without replaying the seed calculation or traversing Releases.

**Blocked by:** 03 — Advance explicit periods with exact Run/Advance equivalence; 07 — Select and protect one Dataset Head atomically; 14 — Execute each Attempt against its start-time Head; 16 — Expand DailyTrack persistence to session coordinates.

**Status:** complete

- [x] Only a successful ResearchRun can start tracking; the Track freezes its complete seed Definition and inherits terminal cash, holdings, NAV, Rebalance phase, pending state, and calculation contracts instead of creating a new all-cash baseline.
- [x] Activation publishes a generation-zero authoritative Checkpoint from the seed Result's Terminal Strategy State and never reloads or reruns the seed Generation.
- [x] Request replay, conflict handling, Active DailyTrack Limit, Definition-edit isolation, Rerun isolation, and terminal Stop semantics remain intact.
- [x] When the seed boundary predates current Head, the Worker processes every unpublished Research Session in chronological order, including several sessions contained in one Generation.
- [x] Catch-up requires only the last successful Checkpoint session and current Head frontier, not a Dataset Release predecessor chain.
- [x] One Tracking Advance Attempt pins its Generation; a later Head move waits for a subsequent Advance rather than altering the running calculation.
- [x] Tracking Head and one complete Checkpoint move atomically only after all sessions owned by the Advance succeed; output matches the pure Run/Advance reference.
- [x] Real Start Tracking HTTP and Worker acceptance with PostgreSQL, RustFS, a temporary mount, and a pure Run/Advance reference proves activation and catch-up; public Track list and detail show origin, strategy session, current progress, and read-only analysis without Release history, Generation browsing, private progression Attempt, Checkpoint manifest, or manual Advance controls.
