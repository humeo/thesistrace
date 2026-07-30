# 26 — Continue DailyTrack through a Historical Correction Boundary

**What to build:** Let the operator publish a Dataset Release containing an
accepted historical correction and see an affected DailyTrack continue through
an ordinary Advance in its current Tracking Generation, preserving committed
history and state while exposing one auditable Tracking Correction Boundary
through the Checkpoint, public API, and Web UI.

**Blocked by:** Bounded Research Storage 05 — Advance DailyTrack from the
bounded Working Cache; Bounded Research Storage 07 — Rebuild invalid Working
Caches within bounded windows.

**Status:** resolved

- [x] An affecting correction creates an Advance in the current Generation whose successful Checkpoint directly follows the prior Head and processes only newly appended Research Sessions.
- [x] The Checkpoint, DailyTrack API, and Web UI identify the Tracking Correction Boundary, its target Dataset Release, and the accepted correction change-set.
- [x] Previously published Strategy observations, Factor summaries, Terminal Strategy State, and pending Strategy decisions remain unchanged; only values first calculated at or after the boundary use corrected data.
- [x] A correction outside the Track's dependency closure advances normally without a Correction Boundary, while only a result-changing calculation-kernel correction can create a new Generation.
- [x] Failed, retried, and duplicate deliveries preserve the prior Head and one logical Advance and never produce a replay root or duplicate Checkpoint.
