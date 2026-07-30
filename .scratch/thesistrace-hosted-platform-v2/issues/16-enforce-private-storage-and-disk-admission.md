# 16 — Enforce private storage and disk admission

**What to build:** Admit or reject payload-growing work from authoritative
compressed-byte accounting and node disk pressure so accepted publication is
atomic, prior truth remains readable, and control operations remain available
under pressure.

**Blocked by:** 09 — Enforce the Personal Workspace Quota Profile; 12 — Advance DailyTrack through finite Workflows; `thesistrace-bounded-research-storage/06 — Contract to the one-MiB Result Bundle`.

**Status:** ready-for-agent

- [ ] PostgreSQL object indexes account for exact compressed bytes owned or referenced by each Personal Workspace without charging platform-owned Dataset Releases.
- [ ] New private payload growth is rejected with the storage-quota dimension before exceeding the effective `10 GiB` limit, and an idempotent retry does not reserve bytes twice.
- [ ] The configured 200-GB persistent SSD emits warning at 70%, rejects new private payload-growing work at 80%, and rejects all payload growth including Dataset Publication at 90%.
- [ ] Reads, cancellation, deletion, cleanup, and the bounded control writes they require remain available at every disk-pressure level.
- [ ] Result Bundle, Tracking Checkpoint, and Dataset Release publication repeat authoritative quota and disk checks immediately before one atomic manifest commit.
- [ ] A failed final check publishes no partial resource, removes temporary unreferenced objects, and leaves the previously authoritative result or Dataset Release available.
- [ ] Quota and disk-pressure acceptance verifies exact stored bytes through production indexes and distinguishes these failures from rate limiting, research validation, and Worker resource exhaustion.
