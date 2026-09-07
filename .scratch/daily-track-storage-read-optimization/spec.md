# Daily Track checkpoint compression and bounded detail reads

Status: ready-for-agent

Implement the user-approved plan in three independent commits. Keep public HTTP/MCP
and page results unchanged. Preserve all immutable checkpoints and both finalized
and continuation account positions. No migration, compatibility reader, fallback,
history cleanup, deployment or merge. Work only in the isolated worktree created
from 6825d4562c2ac9a643028b683e06c37693631465; never change thesistrace-dev data.

1. Publication owns CompressedJsonPayload: canonical JSON, gzip level 9, mtime 0,
   no filename, deterministic headers. Stored bytes own the hash and byte count;
   descriptor declares canonical-json-gzip/version/uncompressed bytes. Verify before
   bounded decompression (64 MiB); reject unknown format, corruption, trailing data,
   truncation and noncanonical decoded JSON. DailyTrack uses only this encoding.
2. Add tracking_observation_state to activation/advance checkpoints, upgrade their
   contracts. Preserve prefix before the replaceable boundary: session, peak NAV,
   maximum drawdown. Start at Tracking Origin NAV, recompute corrected boundary and
   appended dates using accounting Decimal precision. Publish atomically with Head.
3. Read detail from one authority snapshot, current summaries and only checkpoint /
   seed partitions intersecting the latest 504 sessions. Later boundary corrections
   override earlier rows. Preserve snapshot-bound pagination, independent full-chain
   verification, original-origin returns, and lifetime tracking drawdown. Do not load
   complete attempts/progressions/accounts for normal detail.

Acceptance: deterministic codec and malformed inputs; real PostgreSQL/RustFS
publish/recover/delete and physical-byte evidence; full-history independent metric
reference including corrected boundaries, multi-day and >504-session history;
retry/cancel/fencing/restart/ownership/deleted seed and concurrent reads; benchmarks
at 10/250/1000 advances measuring DB data, object bytes and latency; browser DailyTrack
acceptance; final pnpm check and pnpm test:image-smoke. Each issue is reviewed, fixed,
verified and committed separately; complete only after its acceptance passes.
